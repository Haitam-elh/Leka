"""Database access for the capabilities module.

The only place in this module where a query is written (architecture rule 4).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.models import (
    CapabilityEvent,
    CapabilityFavourite,
    CapabilityRegistration,
    WorkspaceCapability,
)
from leka.connectors import Source, SourceStatus

# A source LEKA reads from: connected, even when it is struggling.
CONNECTED = (SourceStatus.ACTIVE, SourceStatus.DEGRADED)


class CapabilityRunRepository:
    """Reads and writes the record of agent runs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session


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
