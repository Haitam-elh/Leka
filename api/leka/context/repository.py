"""Database access for the context module (LEKA-370).

The only place in this module where a query is written (architecture rule 4).
Retrieval of what a context is made of goes through leka.knowledge; this
reads and writes the contexts themselves — their versions and elements.
Ranking does not live here: that is a decision, and decisions belong in
service.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select

from leka.context.models import Context, ContextElement, ContextVersion
from leka.db import WorkspaceScopedRepository


@dataclass(frozen=True)
class ContextFilters:
    status: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None


class ContextRepository(WorkspaceScopedRepository):
    """A workspace's contexts, their versions, and what each holds."""

    async def context(self, context_id: uuid.UUID) -> Context | None:
        return await self.get(Context, context_id)

    async def locked(self, context_id: uuid.UUID) -> Context | None:
        """A context, held until the transaction ends: two refreshes at once
        must not both make the same version."""
        found = await self.list(
            self.select(Context).where(Context.id == context_id).with_for_update()
        )
        return found[0] if found else None

    def contexts(self, filters: ContextFilters) -> Select[tuple[Context]]:
        """The contexts, for a page: by state, by subject."""
        statement = self.select(Context)
        if filters.status:
            statement = statement.where(Context.status == filters.status)
        if filters.subject_type:
            statement = statement.where(Context.subject_type == filters.subject_type)
        if filters.subject_id:
            statement = statement.where(Context.subject_id == filters.subject_id)
        return statement

    def versions(self, context_id: uuid.UUID) -> Select[tuple[ContextVersion]]:
        """A context's versions, for a page."""
        return self.select(ContextVersion).where(ContextVersion.context_id == context_id)

    async def version(self, context_id: uuid.UUID, number: int) -> ContextVersion | None:
        found = await self.list(self.versions(context_id).where(ContextVersion.version == number))
        return found[0] if found else None

    async def latest(
        self,
        context_id: uuid.UUID,
        *,
        assembled: bool = False,
        at: datetime | None = None,
    ) -> ContextVersion | None:
        """Its latest version — the latest that holds something, when
        `assembled` — or the one that stood at `at`."""
        statement = self.versions(context_id)
        if assembled:
            statement = statement.where(ContextVersion.status == "assembled")
        if at is not None:
            statement = statement.where(ContextVersion.assembled_at <= at)
        found = await self.list(statement.order_by(ContextVersion.version.desc()).limit(1))
        return found[0] if found else None

    async def elements(self, version_id: uuid.UUID) -> Sequence[ContextElement]:
        """What a version holds, in order."""
        return await self.list(
            self.select(ContextElement)
            .where(ContextElement.version_id == version_id)
            .order_by(ContextElement.position)
        )

    def keep(self, context: Context) -> None:
        self.add(context)

    async def reload(self, context: Context) -> None:
        """Write, then read back what PostgreSQL computed (updated_at)."""
        await self.flush()
        await self._session.refresh(context)

    async def record(self, version: ContextVersion, elements: Sequence[ContextElement]) -> None:
        """A new version and what it holds, written once."""
        self.add(version)
        await self.flush()
        for element in elements:
            element.version_id = version.id
            self.add(element)
        await self.flush()
