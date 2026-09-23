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
from sqlalchemy.exc import IntegrityError

from leka.connectors.base import TEST_BUDGET_SECONDS, ConnectionTestResult, Connector
from leka.connectors.errors import ConnectorError, Diagnostic, DiagnosticCode, diagnose
from leka.connectors.lifecycle import LifecycleEvent, fingerprint, next_status
from leka.connectors.models import (
    HealthStatus,
    Source,
    SourceEventType,
    SourceKind,
    SourceStatus,
)
from leka.connectors.registry import UnknownConnectorError, get_connector
from leka.connectors.repository import (
    SourceCredentialRepository,
    SourceEventRepository,
    SourceRepository,
)
from leka.connectors.secrets import DatabaseFernetSecretStore, SecretStore

logger = structlog.get_logger(__name__)


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
        self._sources = SourceRepository(session, workspace_id)
        self._events = SourceEventRepository(session, workspace_id)
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
        return result, None

    async def activate(self, source: Source) -> Source:
        tested = source.tested_config_fingerprint
        new_status = next_status(source.status, LifecycleEvent.ACTIVATE)
        if tested is None or tested != await self._fingerprint(source):
            raise ActivationRefusedError(str(source.id))
        source.status = new_status
        self._record(source, SourceEventType.ACTIVATED)
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
