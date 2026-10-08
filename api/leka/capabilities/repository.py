"""Database access for the capabilities module.

The only place in this module where a query is written (architecture rule 4).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.models import (
    AgentRun,
    AgentRunEvent,
    CapabilityEvent,
    CapabilityFavourite,
    CapabilityRegistration,
    ModelCall,
    WorkspaceCapability,
)
from leka.connectors import Source, SourceStatus

# A source LEKA reads from: connected, even when it is struggling.
CONNECTED = (SourceStatus.ACTIVE, SourceStatus.DEGRADED)


class CapabilityRunRepository:
    """Reads and writes the record of agent runs (LEKA-395) — one
    workspace's."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def add(self, row: AgentRun | AgentRunEvent) -> None:
        self._session.add(row)

    async def run(self, run_id: uuid.UUID, *, lock: bool = False) -> AgentRun | None:
        query = select(AgentRun).where(
            AgentRun.workspace_id == self._workspace_id, AgentRun.id == run_id
        )
        found: AgentRun | None = await self._session.scalar(
            query.with_for_update() if lock else query
        )
        return found

    async def runs(
        self, *, key: str | None = None, status: str | None = None, limit: int = 50
    ) -> Sequence[AgentRun]:
        query = (
            select(AgentRun)
            .where(AgentRun.workspace_id == self._workspace_id)
            .order_by(AgentRun.queued_at.desc(), AgentRun.id)
            .limit(limit)
        )
        if key is not None:
            query = query.where(AgentRun.key == key)
        if status is not None:
            query = query.where(AgentRun.status == status)
        return (await self._session.scalars(query)).all()

    async def events(self, run_id: uuid.UUID) -> Sequence[AgentRunEvent]:
        return (
            await self._session.scalars(
                select(AgentRunEvent)
                .where(
                    AgentRunEvent.workspace_id == self._workspace_id,
                    AgentRunEvent.run_id == run_id,
                )
                .order_by(AgentRunEvent.at, AgentRunEvent.seq)
            )
        ).all()

    async def last_seq(self, run_id: uuid.UUID) -> int:
        found = await self._session.scalar(
            select(func.max(AgentRunEvent.seq)).where(AgentRunEvent.run_id == run_id)
        )
        return int(found or 0)

    async def claim(self, run_id: uuid.UUID, *, at: datetime) -> bool:
        """Queued to running — True for the one worker that wins it."""
        claimed = await self._session.execute(
            update(AgentRun)
            .where(
                AgentRun.workspace_id == self._workspace_id,
                AgentRun.id == run_id,
                AgentRun.status == "queued",
            )
            .values(status="running", started_at=at)
        )
        return bool(claimed.rowcount)  # type: ignore[attr-defined]

    async def finish(self, run_id: uuid.UUID, **values: object) -> bool:
        """Running to how it ended — False when it no longer runs: cancelled
        meanwhile, that stands."""
        done = await self._session.execute(
            update(AgentRun)
            .where(
                AgentRun.workspace_id == self._workspace_id,
                AgentRun.id == run_id,
                AgentRun.status == "running",
            )
            .values(**values)
        )
        return bool(done.rowcount)  # type: ignore[attr-defined]

    async def usage(self, run_id: uuid.UUID) -> tuple[int, int, int, float | None]:
        """Its calls to a model: how many, tokens in and out, what they
        cost — none when a price is not published."""
        row = (
            await self._session.execute(
                select(
                    func.count(ModelCall.id),
                    func.coalesce(func.sum(ModelCall.tokens_in), 0),
                    func.coalesce(func.sum(ModelCall.tokens_out), 0),
                    func.sum(ModelCall.cost_usd),
                    func.count(ModelCall.id).filter(ModelCall.cost_usd.is_(None)),
                ).where(
                    ModelCall.workspace_id == self._workspace_id,
                    ModelCall.ref == f"agent_run:{run_id}",
                )
            )
        ).one()
        calls, tokens_in, tokens_out, cost, unpriced = row
        return int(calls), int(tokens_in), int(tokens_out), None if unpriced else cost


async def stale_runs(
    session: AsyncSession, *, running_before: datetime, queued_before: datetime, limit: int
) -> Sequence[tuple[uuid.UUID, uuid.UUID]]:
    """Every workspace's runs no worker will finish: running since before
    `running_before`, queued since before `queued_before`. The sweep's,
    under system scope."""
    rows = await session.execute(
        select(AgentRun.workspace_id, AgentRun.id)
        .where(
            or_(
                and_(AgentRun.status == "running", AgentRun.started_at < running_before),
                and_(AgentRun.status == "queued", AgentRun.queued_at < queued_before),
            )
        )
        .order_by(AgentRun.queued_at)
        .limit(limit)
    )
    return rows.tuples().all()


class CatalogueRepository:
    """The catalogue's history — LEKA's, no tenant's."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def registrations(self, key: str | None = None) -> Sequence[CapabilityRegistration]:
        query = select(CapabilityRegistration).order_by(
            CapabilityRegistration.key, CapabilityRegistration.registered_at
        )
        if key is not None:
            query = query.where(CapabilityRegistration.key == key)
        return (await self._session.scalars(query)).all()

    async def events(self, key: str, *, limit: int = 100) -> Sequence[CapabilityEvent]:
        return (
            await self._session.scalars(
                select(CapabilityEvent)
                .where(CapabilityEvent.key == key)
                .order_by(CapabilityEvent.at.desc(), CapabilityEvent.id)
                .limit(limit)
            )
        ).all()

    async def refused(self, key: str, version: str) -> Sequence[CapabilityEvent]:
        return (
            await self._session.scalars(
                select(CapabilityEvent).where(
                    CapabilityEvent.key == key,
                    CapabilityEvent.version == version,
                    CapabilityEvent.kind == "refused",
                )
            )
        ).all()

    def add(self, row: CapabilityRegistration | CapabilityEvent) -> None:
        self._session.add(row)


class WorkspaceCatalogueRepository:
    """One workspace's say on the catalogue, and what it has connected."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def settings(self) -> dict[str, WorkspaceCapability]:
        rows = await self._session.scalars(
            select(WorkspaceCapability).where(
                WorkspaceCapability.workspace_id == self._workspace_id
            )
        )
        return {row.key: row for row in rows}

    async def setting(self, key: str, *, lock: bool = False) -> WorkspaceCapability | None:
        query = select(WorkspaceCapability).where(
            WorkspaceCapability.workspace_id == self._workspace_id,
            WorkspaceCapability.key == key,
        )
        found: WorkspaceCapability | None = await self._session.scalar(
            query.with_for_update() if lock else query
        )
        return found

    async def favourites(self, user_id: uuid.UUID) -> set[str]:
        rows = await self._session.scalars(
            select(CapabilityFavourite.key).where(
                CapabilityFavourite.workspace_id == self._workspace_id,
                CapabilityFavourite.user_id == user_id,
            )
        )
        return set(rows)

    async def favourite(self, user_id: uuid.UUID, key: str) -> CapabilityFavourite | None:
        found: CapabilityFavourite | None = await self._session.scalar(
            select(CapabilityFavourite).where(
                CapabilityFavourite.workspace_id == self._workspace_id,
                CapabilityFavourite.user_id == user_id,
                CapabilityFavourite.key == key,
            )
        )
        return found

    async def connected(self) -> set[str]:
        """The kinds of the sources it reads from."""
        rows = await self._session.scalars(
            select(Source.kind).where(
                Source.workspace_id == self._workspace_id, Source.status.in_(CONNECTED)
            )
        )
        return {str(getattr(kind, "value", kind)) for kind in rows}

    def new_setting(self, key: str, *, at: datetime) -> WorkspaceCapability:
        row = WorkspaceCapability(
            workspace_id=self._workspace_id, id=uuid.uuid4(), key=key, enabled=True, changed_at=at
        )
        self._session.add(row)
        return row

    def new_favourite(self, user_id: uuid.UUID, key: str) -> CapabilityFavourite:
        row = CapabilityFavourite(
            workspace_id=self._workspace_id, id=uuid.uuid4(), user_id=user_id, key=key
        )
        self._session.add(row)
        return row

    async def remove(self, row: CapabilityFavourite) -> None:
        await self._session.delete(row)

    @staticmethod
    def stamp(
        row: WorkspaceCapability,
        *,
        enabled: bool,
        reason: str | None,
        by: uuid.UUID,
        at: datetime,
    ) -> None:
        row.enabled = enabled
        row.reason = reason
        row.changed_by = by
        row.changed_at = at
