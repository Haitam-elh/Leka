"""The lifecycle of a source: the one place that decides.

Everything a route or a job does to a source goes through SourceService:
validate against the connector's schemas, store the secret through the
SecretStore, run the connector within its time budget, move the status
through leka.connectors.lifecycle, and write the event. Vendor specifics
stay in the connector; this module never names a vendor.

A connector is built here, from credentials decrypted here, for one call,
and dropped. Nothing holds a plaintext longer than that.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import Select
from sqlalchemy.exc import IntegrityError

from leka.background import publish_event
from leka.connectors.base import (
    TEST_BUDGET_SECONDS,
    ConnectionTestResult,
    Connector,
    ScopeListing,
)
from leka.connectors.demo import replayed
from leka.connectors.errors import ConnectorError, Diagnostic, DiagnosticCode, diagnose
from leka.connectors.lifecycle import LifecycleEvent, fingerprint, next_status
from leka.connectors.models import (
    HealthStatus,
    Source,
    SourceEventType,
    SourceKind,
    SourceSettingsVersion,
    SourceStatus,
)
from leka.connectors.registry import UnknownConnectorError, get_connector
from leka.connectors.repository import (
    SourceCredentialRepository,
    SourceEventRepository,
    SourceRepository,
    SourceSettingsRepository,
)
from leka.connectors.secrets import DatabaseFernetSecretStore, SecretStore
from leka.connectors.settings import Finding, SourceSettings, check
from leka.platform import Workspace

logger = structlog.get_logger(__name__)

# What a source lets LEKA write — never what it reads: changed alone, they
# need no new test (GitHub's pull requests, Jira's issues, Confluence's pages).
WRITE_FLAGS = frozenset({"pull_requests", "issues", "pages"})


class SourceNotFoundError(LookupError):
    """No such source in this workspace — including one in another workspace."""


class InvalidSourceInputError(ValueError):
    """Config or credentials that the connector's schema refuses."""

    def __init__(self, part: str, error: ValidationError) -> None:
        super().__init__(f"invalid {part}")
        # Field and message only: `input` would echo a credential back.
        self.fields = [
            (f"{part}." + ".".join(str(loc) for loc in item["loc"]), item["msg"])
            for item in error.errors(include_input=False, include_url=False)
        ]


class DuplicateSourceError(ValueError):
    """Another source of this type already has this name here."""


class NoScopeError(Exception):
    """This connector has no scope to choose from."""


class InvalidSettingsError(ValueError):
    """Settings with errors in them: refused, with every finding."""

    def __init__(self, findings: list[Finding]) -> None:
        super().__init__(f"{len(findings)} findings")
        self.findings = findings


class SettingsConflictError(Exception):
    """Two saves of the same source's settings at once: one lost."""


class ActivationRefusedError(Exception):
    """No successful test for the settings the source has now."""


_HEALTH_EVENT = {
    HealthStatus.HEALTHY: LifecycleEvent.HEALTHY,
    HealthStatus.DEGRADED: LifecycleEvent.DEGRADED,
    HealthStatus.UNHEALTHY: LifecycleEvent.UNHEALTHY,
}


def _validate(schema: type[BaseModel], part: str, data: object) -> BaseModel:
    try:
        return schema.model_validate(data)
    except ValidationError as error:
        raise InvalidSourceInputError(part, error) from error


class SourceService:
    def __init__(
        self,
        session: Any,
        workspace_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID | None,
        transport: httpx.AsyncBaseTransport | None = None,
        secrets: SecretStore | None = None,
    ) -> None:
        self._session = session
        self._sources = SourceRepository(session, workspace_id)
        self._events = SourceEventRepository(session, workspace_id)
        self._settings = SourceSettingsRepository(session, workspace_id)
        self._secrets: SecretStore = secrets or DatabaseFernetSecretStore(
            SourceCredentialRepository(session, workspace_id)
        )
        self._actor = actor_user_id
        self._transport = transport

    # ── reading ──────────────────────────────────────────────────────────────

    @property
    def repository(self) -> SourceRepository:
        return self._sources

    @property
    def events(self) -> SourceEventRepository:
        return self._events

    @property
    def secrets(self) -> SecretStore:
        return self._secrets

    async def get(self, source_id: uuid.UUID) -> Source:
        source = await self._sources.find(source_id)
        if source is None:
            raise SourceNotFoundError(str(source_id))
        return source

    # ── writing ──────────────────────────────────────────────────────────────

    async def create(
        self, kind: SourceKind, name: str, config: dict[str, object], credentials: dict[str, str]
    ) -> Source:
        manifest = get_connector(kind).manifest
        valid_config = _validate(manifest.config_schema, "config", config)
        valid_credentials = _validate(manifest.credentials_schema, "credentials", credentials)

        source = Source(
            kind=kind,
            name=name,
            status=SourceStatus.DRAFT,
            config=valid_config.model_dump(mode="json"),
            created_by=self._actor,
        )
        self._sources.stage(source)
        try:
            await self._sources.flush()
        except IntegrityError as error:
            raise DuplicateSourceError(name) from error
        stored = await self._secrets.put(source.id, valid_credentials)
        self._record(source, SourceEventType.CREATED, kind=kind.value, hint=stored.hint)
        return source

    async def update(
        self, source: Source, *, name: str | None, config: dict[str, object] | None
    ) -> Source:
        if name is not None:
            source.name = name
        if config is not None:
            manifest = get_connector(source.kind).manifest
            new = _validate(manifest.config_schema, "config", config).model_dump(mode="json")
            if new != source.config:
                changed = sorted(
                    k for k in set(new) | set(source.config) if new.get(k) != source.config.get(k)
                )
                if set(changed) <= WRITE_FLAGS:
                    # What LEKA may write, not what it reads: the source stays
                    # as it is, its last test still holds (2026-10-18: allowing
                    # tickets sent a connected Jira back to draft).
                    held = source.tested_config_fingerprint is not None and (
                        source.tested_config_fingerprint == await self._fingerprint(source)
                    )
                    source.config = new
                    if held:
                        source.tested_config_fingerprint = await self._fingerprint(source)
                    self._record(source, SourceEventType.RECONFIGURED, fields=changed, writes=True)
                else:
                    source.config = new
                    self._reconfigure(source)
                    self._record(source, SourceEventType.RECONFIGURED, fields=sorted(new))
        try:
            await self._sources.flush()
        except IntegrityError as error:
            raise DuplicateSourceError(source.name) from error
        await self._sources.refresh(source)
        return source

    async def rotate_credentials(self, source: Source, credentials: dict[str, str]) -> Source:
        manifest = get_connector(source.kind).manifest
        valid = _validate(manifest.credentials_schema, "credentials", credentials)
        stored = await self._secrets.put(source.id, valid)
        self._reconfigure(source)
        self._record(source, SourceEventType.CREDENTIALS_ROTATED, hint=stored.hint)
        return source

    async def test(self, source: Source) -> tuple[ConnectionTestResult | None, Diagnostic | None]:
        """Run the connector's test within its budget. Never raises a ConnectorError."""
        try:
            connector = await self._build(source)
            async with asyncio.timeout(TEST_BUDGET_SECONDS):
                result = await connector.test_connection()
        except ConnectorError as error:
            return None, self._test_failed(source, error.diagnostic)
        except TimeoutError:
            return None, self._test_failed(source, diagnose(DiagnosticCode.TIMEOUT).diagnostic)

        source.status = next_status(source.status, LifecycleEvent.TEST_SUCCEEDED)
        source.tested_config_fingerprint = await self._fingerprint(source)
        source.capabilities = [capability.value for capability in result.capabilities]
        source.source_metadata = result.metadata
        source.last_error = None
        self._record(
            source,
            SourceEventType.TEST_SUCCEEDED,
            account=result.account,
            capabilities=source.capabilities,
            warnings=result.warnings,
        )
        # A test that passed proves the source answers now: a failed health
        # check from before it is stale, not « En panne » beside « Connexion
        # réussie » until the next scheduled check (LEKA-469).
        if source.health_status is HealthStatus.UNHEALTHY:
            source.health_status = HealthStatus.HEALTHY
            source.last_health_check_at = datetime.now(UTC)
            self._record(
                source,
                SourceEventType.HEALTH_CHANGED,
                previous=HealthStatus.UNHEALTHY.value,
                current=HealthStatus.HEALTHY.value,
                code=None,
            )
        return result, None

    async def scope_options(self, source: Source) -> tuple[ScopeListing | None, Diagnostic | None]:
        """Ask the vendor what the scope can be chosen from, within the test's
        budget. Changes nothing on the source and records nothing: it reads."""
        try:
            connector = await self._build(source)
            async with asyncio.timeout(TEST_BUDGET_SECONDS):
                return await connector.list_scope(), None
        except NotImplementedError as error:
            raise NoScopeError(source.kind.value) from error
        except ConnectorError as error:
            return None, error.diagnostic
        except TimeoutError:
            return None, diagnose(DiagnosticCode.TIMEOUT).diagnostic

    # ── settings: scope rules and mapping (LEKA-351) ─────────────────────────

    async def settings(self, source: Source) -> tuple[int, SourceSettings]:
        """The current version and settings. Version 0: never set, the defaults."""
        row = await self._settings.current(source.id)
        if row is None:
            return 0, SourceSettings()
        return row.version, SourceSettings.model_validate(
            {"scope": row.scope, "mapping": row.mapping, "retention": row.retention}
        )

    def settings_history(self, source: Source) -> Select[tuple[SourceSettingsVersion]]:
        return self._settings.history(source.id)

    async def check_settings(
        self, source: Source, settings: SourceSettings, *, longest: int | None = None
    ) -> list[Finding]:
        """What is wrong or doubtful with these settings — against what the
        source can read and what its credentials can see, asked of the
        vendor within the test's budget, and against `longest`, LEKA's
        retention policy for its kind. Changes nothing."""
        visible: list[str] | None
        try:
            listing, _diagnostic = await self.scope_options(source)
            visible = [option.key for option in listing.options] if listing else None
        except NoScopeError:
            visible = None
        capabilities = frozenset(c.value for c in get_connector(source.kind).manifest.capabilities)
        return check(settings, capabilities=capabilities, visible=visible, longest=longest)

    async def save_settings(
        self, source: Source, settings: SourceSettings, *, longest: int | None = None
    ) -> tuple[int, list[Finding], list[str]]:
        """A new version, if the settings changed and have no error in them.
        Returns the version, the findings (warnings) and what changed:
        `scope`, `mapping`, `retention`. Raises InvalidSettingsError with
        every finding."""
        findings = await self.check_settings(source, settings, longest=longest)
        if any(f.level == "error" for f in findings):
            raise InvalidSettingsError(findings)
        version, current = await self.settings(source)
        changed = [
            section
            for section, differs in (
                ("scope", settings.scope != current.scope),
                ("mapping", settings.mapping != current.mapping),
                ("retention", settings.retention != current.retention),
            )
            if differs
        ]
        if not changed:
            return version, findings, []
        try:
            row = await self._settings.append(
                source.id,
                scope=settings.scope.model_dump(mode="json"),
                mapping=settings.mapping.model_dump(mode="json"),
                retention=settings.retention.model_dump(mode="json", exclude_none=True),
                created_by=self._actor,
            )
        except IntegrityError as error:
            raise SettingsConflictError(str(source.id)) from error
        self._record(source, SourceEventType.SETTINGS_CHANGED, version=row.version, changed=changed)
        if changed == ["mapping"]:
            # Only the mapping: the records are normalised again with it —
            # once this version is committed, never with the old one.
            await publish_event(
                self._session,
                source.workspace_id,
                "source.mapping_changed",
                {"source_id": str(source.id), "version": row.version},
            )
        if "scope" in changed and source.status is SourceStatus.ACTIVE:
            # In this transaction, like an activation: the full pass that reads
            # what came in and sweeps what went out starts only if this
            # version is committed — never with the old rules.
            await publish_event(
                self._session,
                source.workspace_id,
                "source.scope_changed",
                {"source_id": str(source.id), "version": row.version},
            )
        return row.version, findings, changed

    async def activate(self, source: Source) -> Source:
        tested = source.tested_config_fingerprint
        new_status = next_status(source.status, LifecycleEvent.ACTIVATE)
        if tested is None or tested != await self._fingerprint(source):
            raise ActivationRefusedError(str(source.id))
        source.status = new_status
        self._record(source, SourceEventType.ACTIVATED)
        # In this transaction: the first sync starts only if the activation
        # is committed (leka/ingestion/sync.py, run_sync_for_event).
        await publish_event(
            self._session, source.workspace_id, "source.activated", {"source_id": str(source.id)}
        )
        return source

    async def disable(self, source: Source) -> Source:
        source.status = next_status(source.status, LifecycleEvent.DISABLE)
        self._record(source, SourceEventType.DISABLED)
        return source

    async def check_health(self, source: Source) -> Source:
        previous = source.health_status
        diagnostic: Diagnostic | None = None
        try:
            connector = await self._build(source)
            async with asyncio.timeout(TEST_BUDGET_SECONDS):
                health = (await connector.check_health()).status
        except ConnectorError as error:
            health, diagnostic = HealthStatus.UNHEALTHY, error.diagnostic
        except TimeoutError:
            health = HealthStatus.UNHEALTHY
            diagnostic = diagnose(DiagnosticCode.TIMEOUT).diagnostic

        source.health_status = health
        source.last_health_check_at = datetime.now(UTC)
        source.last_error = diagnostic.model_dump(mode="json") if diagnostic else None
        source.status = next_status(source.status, _HEALTH_EVENT[health])
        if health is not previous:
            self._record(
                source,
                SourceEventType.HEALTH_CHANGED,
                previous=previous.value,
                current=health.value,
                code=diagnostic.code.value if diagnostic else None,
            )
        return source

    async def delete(self, source: Source) -> None:
        self._record(source, SourceEventType.DELETED, kind=source.kind.value, name=source.name)
        await self._sources.remove(source)

    async def open_connector(self, source: Source) -> Connector[Any, Any]:
        """The source's connector, its credentials decrypted, for one pass.

        For the sync (leka.ingestion), which reads through it. Raises
        ConnectorError with CONFIG_INVALID when it cannot be built. Hold it
        for the pass and drop it: nothing should keep a plaintext longer.
        """
        return await self._build(source)

    def record(self, source: Source, type_: SourceEventType, **payload: object) -> None:
        """Append to the source's history, for work done outside this service."""
        self._record(source, type_, **payload)

    # ── inside ───────────────────────────────────────────────────────────────

    async def _build(self, source: Source) -> Connector[Any, Any]:
        """Decrypt, validate, instantiate. The only place a plaintext exists."""
        try:
            cls = get_connector(source.kind)
        except UnknownConnectorError as error:
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Aucun connecteur n'est disponible pour ce type de source.",
            ) from error
        workspace = await self._session.get(Workspace, source.workspace_id)
        if workspace is not None and workspace.demo:
            # A demonstration's: Nova Retail's records, replayed (LEKA-449).
            return replayed(cls, cls.manifest.config_schema.model_validate(source.config))
        opened = await self._secrets.open(source.id)
        if opened is None:
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID, message="Aucun identifiant n'est enregistré."
            )
        try:
            config = cls.manifest.config_schema.model_validate(source.config)
            credentials = cls.manifest.credentials_schema.model_validate(opened)
        except ValidationError as error:
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                detail=str(error.errors(include_input=False, include_url=False)),
            ) from error
        return cls(config, credentials, transport=self._transport)

    async def _fingerprint(self, source: Source) -> str:
        stored = await self._secrets.describe(source.id)
        return fingerprint(source.config, stored.rotated_at if stored else None)

    def _reconfigure(self, source: Source) -> None:
        source.status = next_status(source.status, LifecycleEvent.RECONFIGURE)
        source.tested_config_fingerprint = None

    def _test_failed(self, source: Source, diagnostic: Diagnostic) -> Diagnostic:
        source.status = next_status(source.status, LifecycleEvent.TEST_FAILED)
        source.tested_config_fingerprint = None
        source.last_error = diagnostic.model_dump(mode="json")
        self._record(source, SourceEventType.TEST_FAILED, code=diagnostic.code.value)
        logger.info("source_test_failed", source_id=str(source.id), code=diagnostic.code.value)
        return diagnostic

    def _record(self, source: Source, type_: SourceEventType, **payload: object) -> None:
        self._events.append(
            source.id,
            type_,
            actor_user_id=self._actor,
            payload={"status": source.status.value, **payload},
        )
