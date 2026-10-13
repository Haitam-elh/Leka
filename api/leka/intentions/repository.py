"""Database access for the intentions module.

The only place in this module where a query is written (architecture rule 4).
What an intention is linked to is checked through the modules that own it —
leka.context, leka.intelligence, leka.knowledge — never by a query here.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, or_, select

from leka.db import WorkspaceScopedRepository
from leka.intentions.lifecycle import PHASES
from leka.intentions.models import Intention, IntentionAnalysis, IntentionEvent, IntentionLink


@dataclass(frozen=True)
class IntentionFilters:
    # active, scheduled, finished — or archived; none: every one not archived.
    phase: str | None = None
    status: str | None = None
    created_by: uuid.UUID | None = None
    # These words in its title or its text.
    words: str | None = None
    # Linked to this thing: a context, a finding, an entity.
    linked: uuid.UUID | None = None


@dataclass(frozen=True)
class AnalysisBrief:
    number: int
    status: str
    started_at: datetime
    intention_version: int | None
    error: str | None


class IntentionRepository(WorkspaceScopedRepository):
    """Reads and writes intentions, their history and their links."""

    async def intention(self, intention_id: uuid.UUID, *, lock: bool = False) -> Intention | None:
        """One intention — held until the transaction ends when it is about
        to move: two moves at once must not both start from where it was."""
        statement = self.select(Intention).where(Intention.id == intention_id)
        if lock:
            statement = statement.with_for_update()
        found = await self.list(statement)
        return found[0] if found else None

    def intentions(self, filters: IntentionFilters) -> Select[tuple[Intention]]:
        """The intentions, for a page."""
        f = filters
        statement = self.select(Intention)
        if f.phase == "archived":
            statement = statement.where(Intention.archived_at.is_not(None))
        else:
            statement = statement.where(Intention.archived_at.is_(None))
            states = PHASES.get(f.phase) if f.phase else None
            if states is not None:
                statement = statement.where(
                    Intention.status.in_([status.value for status in states])
                )
        if f.status is not None:
            statement = statement.where(Intention.status == f.status)
        if f.created_by is not None:
            statement = statement.where(Intention.created_by == f.created_by)
        if f.words:
            pattern = f"%{f.words}%"
            statement = statement.where(
                or_(Intention.title.ilike(pattern), Intention.text.ilike(pattern))
            )
        if f.linked is not None:
            statement = statement.where(
                Intention.id.in_(
                    select(IntentionLink.intention_id).where(
                        IntentionLink.workspace_id == self.workspace_id,
                        IntentionLink.ref_id == f.linked,
                    )
                )
            )
        return statement

    async def counts(self, *, created_by: uuid.UUID | None = None) -> dict[str, int]:
        """How many by status, not archived — and how many archived."""
        mine = [Intention.created_by == created_by] if created_by is not None else []
        rows = await self._session.execute(
            select(Intention.status, func.count())
            .where(
                Intention.workspace_id == self.workspace_id,
                Intention.archived_at.is_(None),
                *mine,
            )
            .group_by(Intention.status)
        )
        found: dict[str, int] = dict(rows.tuples().all())
        archived = await self._session.execute(
            select(func.count()).where(
                Intention.workspace_id == self.workspace_id,
                Intention.archived_at.is_not(None),
                *mine,
            )
        )
        found["archived"] = int(archived.scalar_one())
        return found

    async def events(self, intention_id: uuid.UUID) -> Sequence[IntentionEvent]:
        """Its history, in the order it happened."""
        return await self.list(
            self.select(IntentionEvent)
            .where(IntentionEvent.intention_id == intention_id)
            .order_by(IntentionEvent.sequence)
        )

    async def links(self, intention_id: uuid.UUID) -> Sequence[IntentionLink]:
        return await self.list(
            self.select(IntentionLink)
            .where(IntentionLink.intention_id == intention_id)
            .order_by(IntentionLink.linked_at, IntentionLink.id)
        )

    async def link(
        self, intention_id: uuid.UUID, kind: str, ref_id: uuid.UUID
    ) -> IntentionLink | None:
        found = await self.list(
            self.select(IntentionLink).where(
                IntentionLink.intention_id == intention_id,
                IntentionLink.kind == kind,
                IntentionLink.ref_id == ref_id,
            )
        )
        return found[0] if found else None

    async def unlink(self, link: IntentionLink) -> None:
        await self._session.delete(link)

    async def flush(self) -> None:
        await self._session.flush()

    async def refresh(self, intention: Intention) -> None:
        """Written, and read back: what the database set — its dates."""
        await self._session.flush()
        await self._session.refresh(intention)

    async def hold(self, key: str) -> None:
        """Held for this key until the transaction ends: two requests with
        the same key, one after the other (LEKA-443)."""
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
        )

    async def by_request_key(self, by: uuid.UUID | None, key: str) -> Intention | None:
        """The intention this person's request with this key made."""
        found = await self.list(
            self.select(Intention).where(
                Intention.request_key == key,
                Intention.created_by.is_(None) if by is None else Intention.created_by == by,
            )
        )
        return found[0] if found else None

    async def running_analyses(self, intention_id: uuid.UUID) -> Sequence[IntentionAnalysis]:
        """Its analyses still running — held: one is about to be said
        stopped (LEKA-443)."""
        return await self.list(
            self.select(IntentionAnalysis)
            .where(
                IntentionAnalysis.intention_id == intention_id,
                IntentionAnalysis.status == "running",
            )
            .with_for_update()
        )

    async def last_moves(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, IntentionEvent]:
        """The move that brought each to where it stands (LEKA-443)."""
        if not ids:
            return {}
        rows = await self.list(
            self.select(IntentionEvent)
            .where(IntentionEvent.intention_id.in_(ids), IntentionEvent.kind == "moved")
            .order_by(IntentionEvent.intention_id, IntentionEvent.sequence.desc())
            .distinct(IntentionEvent.intention_id)
        )
        return {row.intention_id: row for row in rows}

    async def latest_analyses(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, AnalysisBrief]:
        """Each one's latest analysis, briefly — not what it found (LEKA-443)."""
        if not ids:
            return {}
        rows = await self._session.execute(
            select(
                IntentionAnalysis.intention_id,
                IntentionAnalysis.number,
                IntentionAnalysis.status,
                IntentionAnalysis.started_at,
                IntentionAnalysis.intention_version,
                IntentionAnalysis.error,
            )
            .where(
                IntentionAnalysis.workspace_id == self.workspace_id,
                IntentionAnalysis.intention_id.in_(ids),
            )
            .order_by(IntentionAnalysis.intention_id, IntentionAnalysis.number.desc())
            .distinct(IntentionAnalysis.intention_id)
        )
        return {row[0]: AnalysisBrief(*row[1:]) for row in rows.tuples()}

    async def analyses(self, intention_id: uuid.UUID, *, limit: int) -> Sequence[IntentionAnalysis]:
        """Its analyses (LEKA-388), the latest first."""
        return await self.list(
            self.select(IntentionAnalysis)
            .where(IntentionAnalysis.intention_id == intention_id)
            .order_by(IntentionAnalysis.number.desc())
            .limit(limit)
        )
