"""The catalogue (LEKA-393): what LEKA can do, with its history — every
version registered, every move of its lifecycle — and, for one workspace and
one person, whether each can be used now.

    definitions() ──▶ sync()       each version registered once, as what it
                                   is; a new one supersedes the last; a move
                                   its lifecycle allows, kept; a change
                                   without a new version, an older version,
                                   a move it forbids — refused, said, and
                                   what was registered stands
                 ──▶ standings()   each capability as the catalogue holds it
                 ──▶ entries()     for a workspace and a person: enabled or
                                   not, its sources connected, a model, the
                                   permission — every reason it cannot run
                 ──▶ discover()    what answers a router's question, ranked

The sync runs when the API starts and every hour (capability-registry-sync):
one at a time, under a lock.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.definition import (
    Availability,
    Definition,
    Lifecycle,
    Match,
    Query,
    Situation,
    availability,
    discover,
    may_move,
    semver,
)
from leka.capabilities.gateway import Gateway, Needs, Route
from leka.capabilities.models import (
    CapabilityEvent,
    CapabilityRegistration,
    WorkspaceCapability,
)
from leka.capabilities.registry import catalogue
from leka.capabilities.repository import CatalogueRepository, WorkspaceCatalogueRepository
from leka.db import load_schema, session_factory, system_scope

logger = structlog.get_logger(__name__)

# One sync at a time, across every process.
LOCK = 393_001


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


# ── its history ──────────────────────────────────────────────────────────────


def _event(
    definition: Definition,
    kind: str,
    at: datetime,
    *,
    before: str | None = None,
    after: str | None = None,
    detail: Mapping[str, object] | None = None,
) -> CapabilityEvent:
    return CapabilityEvent(
        id=uuid.uuid4(),
        key=definition.key,
        version=definition.version,
        kind=kind,
        from_lifecycle=before,
        to_lifecycle=after,
        at=at,
        detail=dict(detail or {}),
    )


async def sync(
    session: AsyncSession, definitions: Sequence[Definition], *, now: datetime | None = None
) -> dict[str, int]:
    """Every definition registered as what it is — or refused, once, said
    why. Returns what it did."""
    moment = _now(now)
    repo = CatalogueRepository(session)
    rows = list(await repo.registrations())
    by_version = {(r.key, r.version): r for r in rows}
    latest: dict[str, CapabilityRegistration] = {}
    for held in rows:
        if held.key not in latest or semver(held.version) > semver(latest[held.key].version):
            latest[held.key] = held
    counts: Counter[str] = Counter()

    async def refuse(d: Definition, why: str, **detail: object) -> None:
        said = {"why": why, "fingerprint": d.fingerprint(), **detail}
        for earlier in await repo.refused(d.key, d.version):
            if earlier.detail == said:
                return
        repo.add(_event(d, "refused", moment, after=d.lifecycle.value, detail=said))
        logger.warning("capability_refused", key=d.key, version=d.version, why=why)
        counts["refused"] += 1

    for d in definitions:
        fingerprint = d.fingerprint()
        row = by_version.get((d.key, d.version))
        if row is None:
            newest = latest.get(d.key)
            if newest is not None and semver(newest.version) > semver(d.version):
                await refuse(d, "version_regressed", latest=newest.version)
                continue
            fresh = CapabilityRegistration(
                id=uuid.uuid4(),
                key=d.key,
                version=d.version,
                kind=d.kind.value,
                category=d.category,
                lifecycle=d.lifecycle.value,
                fingerprint=fingerprint,
                definition=d.described(),
                registered_at=moment,
                lifecycle_changed_at=moment,
            )
            repo.add(fresh)
            repo.add(_event(d, "registered", moment, after=d.lifecycle.value))
            for older in rows:
                if older.key == d.key and older.superseded_at is None:
                    older.superseded_at = moment
                    repo.add(
                        CapabilityEvent(
                            id=uuid.uuid4(),
                            key=older.key,
                            version=older.version,
                            kind="superseded",
                            at=moment,
                            detail={"by": d.version},
                        )
                    )
            rows.append(fresh)
            latest[d.key] = fresh
            counts["registered"] += 1
        elif row.fingerprint != fingerprint:
            await refuse(d, "changed_without_version")
        elif row.lifecycle != d.lifecycle.value:
            before = Lifecycle(row.lifecycle)
            if not may_move(before, d.lifecycle):
                await refuse(d, "lifecycle_refused", registered=before.value)
                continue
            repo.add(
                _event(d, "lifecycle_changed", moment, before=before.value, after=d.lifecycle.value)
            )
            row.lifecycle = d.lifecycle.value
            row.lifecycle_changed_at = moment
            counts["moved"] += 1
    await session.flush()
    return dict(counts)


async def sync_catalogue(*, now: datetime | None = None) -> dict[str, int] | None:
    """The process's catalogue, registered — None when another process is
    doing it."""
    with system_scope():
        async with session_factory() as session:
            locked = await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:lock)"), {"lock": LOCK}
            )
            if not locked:
                return None
            counts = await sync(session, catalogue(), now=now)
            await session.commit()
    logger.info("capability_catalogue_synced", **counts)
    return counts


def run_catalogue_sync() -> dict[str, int] | None:
    """Entry point for the schedule — every module imported first, so that
    each declares its own capabilities, as in the API."""
    load_schema()
    return asyncio.run(sync_catalogue())


# ── as it stands ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Standing:
    """A capability as the catalogue holds it."""

    definition: Definition  # its lifecycle, the registered one
    registered_at: datetime | None
    lifecycle_changed_at: datetime | None
    refused: str | None
    versions: int


def standings(
    definitions: Sequence[Definition], rows: Sequence[CapabilityRegistration]
) -> list[Standing]:
    """Each definition, reconciled with what was registered: the registered
    lifecycle wins; what was refused is said."""
    found: list[Standing] = []
    for d in definitions:
        mine = [r for r in rows if r.key == d.key]
        row = next((r for r in mine if r.version == d.version), None)
        refused: str | None = None
        lifecycle = d.lifecycle
        if row is None:
            if any(semver(r.version) > semver(d.version) for r in mine):
                refused = "version_regressed"
        else:
            lifecycle = Lifecycle(row.lifecycle)
            if row.fingerprint != d.fingerprint():
                refused = "changed_without_version"
            elif row.lifecycle != d.lifecycle.value and not may_move(lifecycle, d.lifecycle):
                refused = "lifecycle_refused"
        found.append(
            Standing(
                definition=replace(d, lifecycle=lifecycle),
                registered_at=row.registered_at if row else None,
                lifecycle_changed_at=row.lifecycle_changed_at if row else None,
                refused=refused,
                versions=max(len(mine), 1),
            )
        )
    return found


@dataclass(frozen=True)
class Entry:
    """A capability for a workspace and a person."""

    standing: Standing
    availability: Availability
    enabled: bool
    setting: WorkspaceCapability | None
    favourite: bool
    # The model that would run it here, chosen by what it needs (LEKA-394).
    model: Route | None = None

    @property
    def definition(self) -> Definition:
        return self.standing.definition


def needs_of(definition: Definition) -> Needs:
    """What a capability asks of a model, as the router reads it."""
    need = definition.model_needs
    return Needs(
        structured=need.structured,
        tools=need.tools,
        context=need.context,
        quality=need.quality,
    )


class CatalogueService:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        *,
        definitions: Sequence[Definition] | None = None,
        model: bool | None = None,
        gateway: Gateway | None = None,
    ) -> None:
        self._session = session
        self._history = CatalogueRepository(session)
        self._workspace = WorkspaceCatalogueRepository(session, workspace_id)
        self._definitions = definitions
        # Said outright (a test), or asked of the router, per what each needs.
        self._model = model
        self._gateway = gateway or Gateway(session, workspace_id)
        self._routes: dict[Needs, Route | None] = {}

    async def _route(self, definition: Definition) -> Route | None:
        """The model that would run it here — none when none can."""
        needs = needs_of(definition)
        if needs not in self._routes:
            routing = await self._gateway.routing(needs)
            self._routes[needs] = routing.routes[0] if routing.routes else None
        return self._routes[needs]

    def _all(self) -> Sequence[Definition]:
        return self._definitions if self._definitions is not None else catalogue()

    async def standings(self) -> list[Standing]:
        return standings(self._all(), await self._history.registrations())

    async def entries(
        self, *, permissions: frozenset[str], user_id: uuid.UUID | None = None
    ) -> list[Entry]:
        settings = await self._workspace.settings()
        connected = frozenset(await self._workspace.connected())
        favourites = await self._workspace.favourites(user_id) if user_id else set()
        found: list[Entry] = []
        for standing in await self.standings():
            key = standing.definition.key
            setting = settings.get(key)
            enabled = setting.enabled if setting is not None else True
            route = await self._route(standing.definition) if standing.definition.model else None
            situation = Situation(
                enabled=enabled,
                connected=connected,
                model=route is not None if self._model is None else self._model,
                permissions=permissions,
            )
            found.append(
                Entry(
                    standing=standing,
                    availability=availability(
                        standing.definition, situation, refused=standing.refused
                    ),
                    enabled=enabled,
                    setting=setting,
                    favourite=key in favourites,
                    model=route,
                )
            )
        return found

    async def entry(
        self, key: str, *, permissions: frozenset[str], user_id: uuid.UUID | None = None
    ) -> Entry | None:
        return next(
            (
                e
                for e in await self.entries(permissions=permissions, user_id=user_id)
                if e.definition.key == key
            ),
            None,
        )

    async def history(
        self, key: str
    ) -> tuple[Sequence[CapabilityRegistration], Sequence[CapabilityEvent]]:
        return await self._history.registrations(key), await self._history.events(key)

    async def disabled(self) -> frozenset[str]:
        """What the workspace turned off."""
        return frozenset(k for k, s in (await self._workspace.settings()).items() if not s.enabled)

    async def set_enabled(
        self,
        key: str,
        *,
        enabled: bool,
        reason: str | None,
        by: uuid.UUID,
        now: datetime | None = None,
    ) -> bool:
        """Turned on or off for the workspace — False for a capability LEKA
        does not have."""
        if not any(d.key == key for d in self._all()):
            return False
        moment = _now(now)
        row = await self._workspace.setting(key, lock=True)
        if row is None:
            row = self._workspace.new_setting(key, at=moment)
        self._workspace.stamp(row, enabled=enabled, reason=reason, by=by, at=moment)
        await self._session.flush()
        return True

    async def set_favourite(self, key: str, *, user_id: uuid.UUID, on: bool) -> bool:
        """Kept at hand, or not — False for a capability LEKA does not have."""
        if not any(d.key == key for d in self._all()):
            return False
        row = await self._workspace.favourite(user_id, key)
        if on and row is None:
            self._workspace.new_favourite(user_id, key)
        elif not on and row is not None:
            await self._workspace.remove(row)
        await self._session.flush()
        return True

    async def discover(self, query: Query, *, permissions: frozenset[str]) -> list[Match]:
        """What answers a router's question, for this workspace, ranked."""
        entries = await self.entries(permissions=permissions)
        return discover(
            [e.definition for e in entries],
            query,
            {e.definition.key: e.availability for e in entries},
        )
