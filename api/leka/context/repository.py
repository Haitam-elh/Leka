"""Database access for the context module (LEKA-370).

The only place in this module where a query is written (architecture rule 4).
Retrieval of what a context is made of goes through leka.knowledge; this
reads and writes the contexts themselves — their versions and elements.
Ranking does not live here: that is a decision, and decisions belong in
service.py.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, and_, exists, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.context.models import (
    Context,
    ContextCheck,
    ContextElement,
    ContextFeedback,
    ContextFollow,
    ContextVersion,
)
from leka.db import WorkspaceScopedRepository


@dataclass(frozen=True)
class ContextFilters:
    status: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    # Behind the model, or up to date (LEKA-374).
    stale: bool | None = None
    # LEKA-376: holding this entity in its latest version; these words in
    # its title or purpose; its latest version judged so; made by this user.
    holds: uuid.UUID | None = None
    words: str | None = None
    level: str | None = None
    created_by: uuid.UUID | None = None


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
        if filters.stale is True:
            statement = statement.where(
                (Context.stale_since.is_not(None)) | (Context.status == "failed")
            )
        elif filters.stale is False:
            statement = statement.where(Context.stale_since.is_(None), Context.status != "failed")
        if filters.holds is not None:
            statement = statement.where(
                exists(
                    select(ContextElement.id)
                    .join(ContextVersion, ContextVersion.id == ContextElement.version_id)
                    .where(
                        ContextElement.workspace_id == self.workspace_id,
                        ContextElement.ref_id == filters.holds,
                        ContextVersion.context_id == Context.id,
                        ContextVersion.version == Context.current_version,
                    )
                )
            )
        if filters.words:
            said = "%" + _escaped(filters.words) + "%"
            statement = statement.where(
                or_(
                    Context.title.ilike(said, escape="\\"),
                    Context.purpose.ilike(said, escape="\\"),
                )
            )
        if filters.level is not None:
            statement = statement.where(
                exists(
                    select(ContextVersion.id).where(
                        ContextVersion.workspace_id == self.workspace_id,
                        ContextVersion.context_id == Context.id,
                        ContextVersion.version == Context.current_version,
                        ContextVersion.quality["level"].astext == filters.level,
                    )
                )
            )
        if filters.created_by is not None:
            statement = statement.where(Context.created_by == filters.created_by)
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

    @asynccontextmanager
    async def isolated(self, timeout_ms: int) -> AsyncIterator[None]:
        """A savepoint, and a statement timeout inside it (LEKA-371): what a
        retriever reads, it reads alone — an error or a query that takes too
        long undoes it, and only it; the rest of the assembly goes on."""
        savepoint = await self._session.begin_nested()
        try:
            await self._session.execute(
                text(f"SET LOCAL statement_timeout = {max(int(timeout_ms), 1)}")
            )
            yield
        except BaseException:
            await savepoint.rollback()
            raise
        await self._session.execute(text("SET LOCAL statement_timeout TO DEFAULT"))
        await savepoint.commit()

    async def record(self, version: ContextVersion, elements: Sequence[ContextElement]) -> None:
        """A new version and what it holds, written once."""
        self.add(version)
        await self.flush()
        for element in elements:
            element.version_id = version.id
            self.add(element)
        await self.flush()

    # ── keeping up (LEKA-374) ──────────────────────────────────────────────

    async def held(
        self, ids: Sequence[uuid.UUID]
    ) -> list[tuple[uuid.UUID, uuid.UUID, datetime | None]]:
        """Which contexts hold these entities in their latest version that
        holds something — each (context, entity, the build it last read) —
        the archived aside."""
        if not ids:
            return []
        rows = await self._session.execute(
            text(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (v.context_id) v.id, v.context_id
                      FROM context_versions v
                     WHERE v.workspace_id = :workspace AND v.status = 'assembled'
                     ORDER BY v.context_id, v.version DESC
                )
                SELECT DISTINCT c.id, e.ref_id, c.checked_model_at
                  FROM context_elements e
                  JOIN latest ON latest.id = e.version_id
                  JOIN contexts c ON c.id = latest.context_id AND c.workspace_id = :workspace
                 WHERE e.workspace_id = :workspace
                   AND e.kind = 'entity'
                   AND e.ref_id = ANY(CAST(:ids AS uuid[]))
                   AND c.status <> 'archived'
                """
            ),
            {"workspace": self.workspace_id, "ids": list(set(ids))},
        )
        return [(context, entity, at) for context, entity, at in rows.tuples()]

    async def worded(self, limit: int) -> list[tuple[uuid.UUID, str, datetime | None]]:
        """The contexts not archived, the latest used first: their words —
        what they search, or their purpose — and the build each last read."""
        rows = await self._session.execute(
            select(
                Context.id,
                Context.request["query"].astext,
                Context.purpose,
                Context.checked_model_at,
            )
            .where(Context.workspace_id == self.workspace_id, Context.status != "archived")
            .order_by(func.coalesce(Context.used_at, Context.created_at).desc(), Context.id)
            .limit(limit)
        )
        return [
            (context, query or purpose or "", at) for context, query, purpose, at in rows.tuples()
        ]

    async def earliest_checked(self) -> datetime | None:
        """The oldest build a context not archived last read: where
        following starts, the first time."""
        found = await self._session.scalar(
            select(func.min(Context.checked_model_at)).where(
                Context.workspace_id == self.workspace_id, Context.status != "archived"
            )
        )
        return found if isinstance(found, datetime) else None

    async def follow_mark(self) -> ContextFollow | None:
        """Up to which build this workspace's contexts were followed."""
        found = await self.list(self.select(ContextFollow).limit(1))
        return found[0] if found else None

    async def keep_follow_mark(self, at: datetime, run_id: uuid.UUID | None) -> None:
        mark = await self.follow_mark()
        if mark is None:
            self.add(ContextFollow(followed_at=at, run_id=run_id))
        else:
            mark.followed_at = at
            mark.run_id = run_id
        await self.flush()

    async def mark(
        self,
        context_id: uuid.UUID,
        *,
        since: datetime,
        pending: list[dict[str, object]],
        count: int,
    ) -> None:
        """What a context is behind on, said on it. Not a change of the
        context: its `updated_at` stays."""
        await self._session.execute(
            update(Context)
            .where(Context.workspace_id == self.workspace_id, Context.id == context_id)
            .values(
                stale_since=since,
                pending=pending,
                pending_count=count,
                updated_at=Context.updated_at,
            )
            .execution_options(synchronize_session="fetch")
        )

    async def mark_every(self, change: dict[str, object], at: datetime) -> int:
        """Every context not archived, checked before `at`, behind on one
        change — the model changed more than can be said one by one."""
        result = await self._session.execute(
            text(
                """
                UPDATE contexts
                   SET stale_since = coalesce(stale_since, :at),
                       pending = pending || CAST(:change AS jsonb),
                       pending_count = pending_count + 1
                 WHERE workspace_id = :workspace
                   AND status <> 'archived'
                   AND (checked_model_at IS NULL OR checked_model_at < :at)
                """
            ),
            {"workspace": self.workspace_id, "change": json.dumps([change]), "at": at},
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def used(self, context_id: uuid.UUID, at: datetime, *, every: timedelta) -> None:
        """Someone used it: said at most once in `every`. Not a change of
        the context: its `updated_at` stays."""
        await self._session.execute(
            update(Context)
            .where(
                Context.workspace_id == self.workspace_id,
                Context.id == context_id,
                (Context.used_at.is_(None)) | (Context.used_at < at - every),
            )
            .values(used_at=at, updated_at=Context.updated_at)
            .execution_options(synchronize_session="fetch")
        )

    async def due(self, *, active_since: datetime, limit: int) -> list[uuid.UUID]:
        """The contexts to make again: behind the model, following it, used
        since `active_since` — the latest used first."""
        used = func.coalesce(Context.used_at, Context.created_at)
        rows = await self._session.execute(
            select(Context.id)
            .where(
                Context.workspace_id == self.workspace_id,
                Context.stale_since.is_not(None),
                Context.follow.is_(True),
                Context.status != "archived",
                used >= active_since,
            )
            .order_by(used.desc(), Context.id)
            .limit(limit)
        )
        return list(rows.scalars())

    async def standing(
        self, *, used_since: datetime, limit: int
    ) -> list[tuple[Context, dict[str, object] | None]]:
        """Where the contexts in use stand (LEKA-377): each, with the quality
        its latest version was judged — the latest used first."""
        rows = await self._session.execute(
            select(Context, ContextVersion.quality)
            .outerjoin(
                ContextVersion,
                and_(
                    ContextVersion.workspace_id == Context.workspace_id,
                    ContextVersion.context_id == Context.id,
                    ContextVersion.version == Context.current_version,
                ),
            )
            .where(
                Context.workspace_id == self.workspace_id,
                Context.status != "archived",
                Context.used_at >= used_since,
            )
            .order_by(Context.used_at.desc(), Context.id)
            .limit(limit)
        )
        return [(context, quality) for context, quality in rows.tuples()]

    def checks(self, context_id: uuid.UUID) -> Select[tuple[ContextCheck]]:
        """Every time a context was made again, for a page."""
        return self.select(ContextCheck).where(ContextCheck.context_id == context_id)

    def keep_check(self, check: ContextCheck) -> None:
        self.add(check)

    # ── what people say of it (LEKA-375) ───────────────────────────────────

    async def element(self, version_id: uuid.UUID, ref_id: uuid.UUID) -> ContextElement | None:
        """One element of a version."""
        found = await self.list(
            self.select(ContextElement).where(
                ContextElement.version_id == version_id, ContextElement.ref_id == ref_id
            )
        )
        return found[0] if found else None

    def keep_feedback(self, feedback: ContextFeedback) -> None:
        self.add(feedback)

    async def feedback(
        self, context_id: uuid.UUID, version: int, *, limit: int
    ) -> Sequence[ContextFeedback]:
        """What was said of a version, the latest first."""
        return await self.list(
            self.select(ContextFeedback)
            .where(ContextFeedback.context_id == context_id, ContextFeedback.version == version)
            .order_by(ContextFeedback.given_at.desc(), ContextFeedback.id)
            .limit(limit)
        )

    async def feedback_counts(self, context_id: uuid.UUID, version: int) -> dict[str, int]:
        """What was said of a version, counted by verdict."""
        rows = await self._session.execute(
            select(ContextFeedback.verdict, func.count())
            .where(
                ContextFeedback.workspace_id == self.workspace_id,
                ContextFeedback.context_id == context_id,
                ContextFeedback.version == version,
            )
            .group_by(ContextFeedback.verdict)
        )
        return {verdict: int(count) for verdict, count in rows.tuples()}

    async def element_feedback(self, context_id: uuid.UUID, ref_id: uuid.UUID) -> dict[str, int]:
        """What was said of one element, in every version, by verdict."""
        rows = await self._session.execute(
            select(ContextFeedback.verdict, func.count())
            .where(
                ContextFeedback.workspace_id == self.workspace_id,
                ContextFeedback.context_id == context_id,
                ContextFeedback.ref_id == ref_id,
            )
            .group_by(ContextFeedback.verdict)
        )
        return {verdict: int(count) for verdict, count in rows.tuples()}

    async def history(
        self, context_id: uuid.UUID, ref_id: uuid.UUID, *, limit: int
    ) -> list[tuple[ContextVersion, ContextElement | None]]:
        """A context's versions, the latest first, each with the element it
        held as `ref_id` — or none (LEKA-376)."""
        rows = await self._session.execute(
            self.select(ContextVersion)
            .add_columns(ContextElement)
            .outerjoin(
                ContextElement,
                and_(
                    ContextElement.version_id == ContextVersion.id,
                    ContextElement.ref_id == ref_id,
                ),
            )
            .where(ContextVersion.context_id == context_id)
            .order_by(ContextVersion.version.desc())
            .limit(limit)
        )
        return [(version, element) for version, element in rows.tuples()]

    async def checks_after(
        self, context_id: uuid.UUID, after: datetime | None, *, limit: int
    ) -> Sequence[ContextCheck]:
        """Each time a context was made again after `after`, the oldest
        first (LEKA-376: what a stream tells)."""
        statement = self.checks(context_id)
        if after is not None:
            statement = statement.where(ContextCheck.checked_at > after)
        return await self.list(
            statement.order_by(ContextCheck.checked_at, ContextCheck.id).limit(limit)
        )

    async def feedback_since(self, since: datetime, *, limit: int) -> Sequence[ContextFeedback]:
        """What was said of the workspace's contexts since `since`, the
        latest first."""
        return await self.list(
            self.select(ContextFeedback)
            .where(ContextFeedback.given_at >= since)
            .order_by(ContextFeedback.given_at.desc(), ContextFeedback.id)
            .limit(limit)
        )


class ContextSweeper:
    """The contexts of every workspace, for the hourly sweep (job.py). Not
    workspace-scoped, like leka.knowledge's ModelSweeper: it runs under
    system_scope, declared by its caller."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def followed(self, limit: int) -> list[uuid.UUID]:
        """The workspaces with a context to keep up: one not archived,
        following the model — the latest used first."""
        used = func.max(func.coalesce(Context.used_at, Context.created_at))
        rows = await self._session.execute(
            select(Context.workspace_id)
            .where(Context.status != "archived", Context.follow.is_(True))
            .group_by(Context.workspace_id)
            .order_by(used.desc())
            .limit(limit)
        )
        return list(rows.scalars())

    async def prune_checks(self, *, before: datetime) -> int:
        """The checks older than `before`: what triggered them is history
        the versions keep."""
        result = await self._session.execute(
            text("DELETE FROM context_checks WHERE checked_at < :before"), {"before": before}
        )
        return int(getattr(result, "rowcount", 0) or 0)


def _escaped(words: str) -> str:
    """Words as a LIKE pattern takes them: its wildcards said literally."""
    return words.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
