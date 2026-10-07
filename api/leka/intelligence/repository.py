"""Database access for the intelligence module (LEKA-377).

The only place in this module where a query is written (architecture rule
4). What a run reads of the company model and the contexts goes through
leka.knowledge and leka.context; this reads and writes the runs, their
steps, the findings, the enrichment candidates (LEKA-380), the conflicts and
the authority rules (LEKA-382).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import Source, SourceEvent
from leka.db import WorkspaceScopedRepository
from leka.identity import User
from leka.intelligence.models import (
    AuthorityRule,
    EnrichmentCandidate,
    Finding,
    IntelligenceRun,
    IntelligenceStep,
    KnowledgeConflict,
    QualityPoint,
    QualityScoreRow,
)
from leka.knowledge import ModelRun
from leka.platform import Membership

# The most pressing first, and an order that holds between equals.
PRESSING = (
    Finding.rank.desc(),
    Finding.confidence.desc(),
    Finding.subject_name,
    Finding.id,
)


@dataclass(frozen=True)
class FindingFilters:
    status: str | None = None
    severity: str | None = None
    category: str | None = None
    analyzer: str | None = None
    subject_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CandidateFilters:
    status: str | None = None
    family: str | None = None
    analyzer: str | None = None
    subject_id: uuid.UUID | None = None


@dataclass(frozen=True)
class QualityFilters:
    scope: str | None = None
    level: str | None = None
    column: str | None = None
    # The key of an area it counts in: team:<id>, application:<id>…
    area: str | None = None
    subject_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ConflictFilters:
    status: str | None = None
    kind: str | None = None
    subject_id: uuid.UUID | None = None


class IntelligenceRepository(WorkspaceScopedRepository):
    # ── runs ────────────────────────────────────────────────────────────

    def add_run(self, run: IntelligenceRun) -> None:
        self.add(run)

    async def run(self, run_id: uuid.UUID) -> IntelligenceRun | None:
        found = await self._session.execute(
            self.select(IntelligenceRun).where(IntelligenceRun.id == run_id)
        )
        return found.scalar_one_or_none()

    def runs(self) -> Select[tuple[IntelligenceRun]]:
        """The runs, for a page."""
        return self.select(IntelligenceRun)

    async def latest_run(self) -> IntelligenceRun | None:
        found = await self._session.execute(
            self.select(IntelligenceRun)
            .order_by(IntelligenceRun.started_at.desc(), IntelligenceRun.id.desc())
            .limit(1)
        )
        return found.scalar_one_or_none()

    async def steps(self, run_id: uuid.UUID) -> Sequence[IntelligenceStep]:
        found = await self._session.execute(
            self.select(IntelligenceStep)
            .where(IntelligenceStep.run_id == run_id)
            .order_by(IntelligenceStep.started_at, IntelligenceStep.analyzer)
        )
        return found.scalars().all()

    def add_step(self, step: IntelligenceStep) -> None:
        self.add(step)

    # ── findings ────────────────────────────────────────────────────────

    def findings(self, filters: FindingFilters) -> Select[tuple[Finding]]:
        """The findings, for a page: by state, severity, category, analysis,
        what they are about or involve."""
        statement = self.select(Finding)
        if filters.status:
            statement = statement.where(Finding.status == filters.status)
        if filters.severity:
            statement = statement.where(Finding.severity == filters.severity)
        if filters.category:
            statement = statement.where(Finding.category == filters.category)
        if filters.analyzer:
            statement = statement.where(Finding.analyzer == filters.analyzer)
        if filters.subject_id is not None:
            statement = statement.where(Finding.subject_id == filters.subject_id)
        return statement

    async def finding(self, finding_id: uuid.UUID) -> Finding | None:
        found = await self._session.execute(self.select(Finding).where(Finding.id == finding_id))
        return found.scalar_one_or_none()

    async def of_analyzer(self, analyzer: str) -> dict[str, Finding]:
        """An analysis's findings, open and resolved, by key: what a step
        compares what it found with."""
        found = await self._session.execute(
            self.select(Finding).where(Finding.analyzer == analyzer)
        )
        return {finding.key: finding for finding in found.scalars()}

    def add_finding(self, finding: Finding) -> None:
        self.add(finding)

    async def open_counts(self) -> dict[str, int]:
        found = await self._session.execute(
            select(Finding.severity, func.count())
            .where(Finding.workspace_id == self.workspace_id, Finding.status == "open")
            .group_by(Finding.severity)
        )
        return dict(found.tuples().all())

    async def top(self, limit: int) -> Sequence[Finding]:
        """The most pressing open findings, in an order that holds: by rank;
        between equals, the surest, then by name — never by the arbitrary
        order of their ids."""
        found = await self._session.execute(
            self.select(Finding).where(Finding.status == "open").order_by(*PRESSING).limit(limit)
        )
        return found.scalars().all()

    # ── enrichment candidates (LEKA-380) ────────────────────────────────

    def candidates(self, filters: CandidateFilters) -> Select[tuple[EnrichmentCandidate]]:
        """The candidates, for a page: by state, family, analysis, the thing
        they enrich or involve."""
        statement = self.select(EnrichmentCandidate)
        if filters.status:
            statement = statement.where(EnrichmentCandidate.status == filters.status)
        if filters.family:
            statement = statement.where(EnrichmentCandidate.family == filters.family)
        if filters.analyzer:
            statement = statement.where(EnrichmentCandidate.analyzer == filters.analyzer)
        if filters.subject_id is not None:
            thing = filters.subject_id
            statement = statement.where(
                (EnrichmentCandidate.subject_id == thing)
                | (EnrichmentCandidate.start_id == thing)
                | (EnrichmentCandidate.end_id == thing)
            )
        return statement

    async def candidate(
        self, candidate_id: uuid.UUID, *, for_update: bool = False
    ) -> EnrichmentCandidate | None:
        statement = self.select(EnrichmentCandidate).where(EnrichmentCandidate.id == candidate_id)
        if for_update:
            statement = statement.with_for_update()
        found = await self._session.execute(statement)
        return found.scalar_one_or_none()

    async def candidates_of(self, analyzer: str) -> dict[str, EnrichmentCandidate]:
        """An analysis's candidates, whatever their state, by key: what a
        step compares what it proposed with."""
        found = await self._session.execute(
            self.select(EnrichmentCandidate).where(EnrichmentCandidate.analyzer == analyzer)
        )
        return {candidate.key: candidate for candidate in found.scalars()}

    def add_candidate(self, candidate: EnrichmentCandidate) -> None:
        self.add(candidate)

    async def candidate_counts(self) -> list[tuple[str, str, str | None, int]]:
        """(status, family, decided via, how many)."""
        found = await self._session.execute(
            select(
                EnrichmentCandidate.status,
                EnrichmentCandidate.family,
                EnrichmentCandidate.decided_via,
                func.count(),
            )
            .where(EnrichmentCandidate.workspace_id == self.workspace_id)
            .group_by(
                EnrichmentCandidate.status,
                EnrichmentCandidate.family,
                EnrichmentCandidate.decided_via,
            )
        )
        return [(status, family, via, int(n)) for status, family, via, n in found.tuples().all()]

    # ── conflicts and authority (LEKA-382) ───────────────────────────────

    def conflicts(self, filters: ConflictFilters) -> Select[tuple[KnowledgeConflict]]:
        statement = self.select(KnowledgeConflict)
        if filters.status:
            statement = statement.where(KnowledgeConflict.status == filters.status)
        if filters.kind:
            statement = statement.where(KnowledgeConflict.kind == filters.kind)
        if filters.subject_id is not None:
            statement = statement.where(KnowledgeConflict.subject_id == filters.subject_id)
        return statement

    async def conflict(
        self, conflict_id: uuid.UUID, *, for_update: bool = False
    ) -> KnowledgeConflict | None:
        statement = self.select(KnowledgeConflict).where(KnowledgeConflict.id == conflict_id)
        if for_update:
            statement = statement.with_for_update()
        found = await self._session.execute(statement)
        return found.scalar_one_or_none()

    async def all_conflicts(self) -> dict[str, KnowledgeConflict]:
        """Every conflict, whatever its state, by key: what a run compares
        what it found with."""
        found = await self._session.execute(self.select(KnowledgeConflict))
        return {conflict.key: conflict for conflict in found.scalars()}

    def add_conflict(self, conflict: KnowledgeConflict) -> None:
        self.add(conflict)

    async def conflict_counts(self) -> dict[str, int]:
        found = await self._session.execute(
            select(KnowledgeConflict.status, func.count())
            .where(KnowledgeConflict.workspace_id == self.workspace_id)
            .group_by(KnowledgeConflict.status)
        )
        return {status: int(n) for status, n in found.tuples().all()}

    async def authority_rules(self) -> list[tuple[AuthorityRule, Source | None]]:
        """The workspace's rules, each with its source."""
        found = await self._session.execute(
            select(AuthorityRule, Source)
            .outerjoin(
                Source,
                (Source.id == AuthorityRule.source_id)
                & (Source.workspace_id == AuthorityRule.workspace_id),
            )
            .where(AuthorityRule.workspace_id == self.workspace_id)
            .order_by(AuthorityRule.about, AuthorityRule.created_at)
        )
        return [(rule, source) for rule, source in found.tuples().all()]

    async def authority_rule(
        self,
        *,
        rule_id: uuid.UUID | None = None,
        about: str | None = None,
        source_id: uuid.UUID | None = None,
    ) -> AuthorityRule | None:
        statement = self.select(AuthorityRule)
        if rule_id is not None:
            statement = statement.where(AuthorityRule.id == rule_id)
        if about is not None and source_id is not None:
            statement = statement.where(
                AuthorityRule.about == about, AuthorityRule.source_id == source_id
            )
        found = await self._session.execute(statement)
        return found.scalar_one_or_none()

    async def source(self, source_id: uuid.UUID) -> Source | None:
        found = await self._session.execute(
            select(Source).where(Source.workspace_id == self.workspace_id, Source.id == source_id)
        )
        return found.scalar_one_or_none()

    def add_rule(self, rule: AuthorityRule) -> None:
        self.add(rule)

    async def delete_rule(self, rule: AuthorityRule) -> None:
        await self._session.delete(rule)

    async def about(self, ids: Sequence[uuid.UUID], *, limit: int) -> Sequence[Finding]:
        """The open findings about these things — for a service downstream
        to say what LEKA already concluded about what it is looking at."""
        if not ids:
            return []
        found = await self._session.execute(
            self.select(Finding)
            .where(Finding.status == "open", Finding.subject_id.in_(list(ids)))
            .order_by(*PRESSING)
            .limit(limit)
        )
        return found.scalars().all()


@dataclass(frozen=True)
class Standing:
    """Where a workspace's analysis stands, for the sweep: its model's
    latest build, its latest run's basis and catalogue."""

    workspace_id: uuid.UUID
    built_at: datetime | None
    analysed_at: datetime | None
    analysed_built_at: datetime | None
    catalogue: str | None


class IntelligenceSweeper:
    """Across workspaces, for the hourly sweep: who is behind, what is
    stuck, what is old. Not a workspace's repository — the sweep serves
    them all, under the system scope."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def standings(self) -> list[Standing]:
        """Every workspace with a built model, and where its analysis stands."""
        built = (
            select(
                ModelRun.workspace_id.label("workspace_id"),
                func.max(ModelRun.finished_at).label("built_at"),
            )
            .where(ModelRun.status == "succeeded")
            .group_by(ModelRun.workspace_id)
            .subquery()
        )
        latest = (
            select(
                IntelligenceRun.workspace_id,
                IntelligenceRun.started_at,
                IntelligenceRun.model_built_at,
                IntelligenceRun.catalogue,
            )
            .where(IntelligenceRun.status.in_(("succeeded", "partial")))
            .distinct(IntelligenceRun.workspace_id)
            .order_by(IntelligenceRun.workspace_id, IntelligenceRun.started_at.desc())
            .subquery()
        )
        rows = await self._session.execute(
            select(
                built.c.workspace_id,
                built.c.built_at,
                latest.c.started_at,
                latest.c.model_built_at,
                latest.c.catalogue,
            ).outerjoin(latest, latest.c.workspace_id == built.c.workspace_id)
        )
        return [Standing(*row) for row in rows.tuples()]

    async def abandon_stuck(self, *, before: datetime, at: datetime) -> int:
        """Runs a dead worker left `running`: abandoned, said so."""
        result = await self._session.execute(
            update(IntelligenceRun)
            .where(IntelligenceRun.status == "running", IntelligenceRun.started_at < before)
            .values(status="abandoned", finished_at=at, error="WorkerLost")
            .execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def prune_runs(self, *, before: datetime) -> int:
        """Runs older than `before`, and their steps — never a workspace's
        latest. Findings keep their run ids: they say what saw them."""
        latest = (
            select(IntelligenceRun.id)
            .distinct(IntelligenceRun.workspace_id)
            .order_by(IntelligenceRun.workspace_id, IntelligenceRun.started_at.desc())
        )
        result = await self._session.execute(
            delete(IntelligenceRun)
            .where(IntelligenceRun.started_at < before, IntelligenceRun.id.not_in(latest))
            .execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def prune_resolved(self, *, before: datetime) -> int:
        """Findings resolved before `before`: what was true long ago — and
        candidates withdrawn, unseen since then (LEKA-380). A decision is
        kept: it says why the model is what it is."""
        result = await self._session.execute(
            delete(Finding)
            .where(Finding.status == "resolved", Finding.resolved_at < before)
            .execution_options(synchronize_session=False)
        )
        withdrawn = await self._session.execute(
            delete(EnrichmentCandidate)
            .where(
                EnrichmentCandidate.status == "withdrawn",
                EnrichmentCandidate.last_seen_at < before,
            )
            .execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0) + int(
            getattr(withdrawn, "rowcount", 0) or 0
        )

    async def prune_quality(self, *, before: datetime) -> int:
        """Quality history older than `before` (LEKA-381). A score as it
        stands is never pruned."""
        result = await self._session.execute(
            delete(QualityPoint)
            .where(QualityPoint.measured_at < before)
            .execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)


class QualityRepository(WorkspaceScopedRepository):
    """Knowledge quality (LEKA-381): the scores as they stand, and their
    history."""

    async def current(self) -> dict[str, QualityScoreRow]:
        """Every score as it stands, by key: what a run compares with."""
        found = await self._session.execute(self.select(QualityScoreRow))
        return {row.key: row for row in found.scalars()}

    async def forget(self, rows: Sequence[QualityScoreRow]) -> None:
        for row in rows:
            await self._session.delete(row)

    def scores(self, filters: QualityFilters) -> Select[tuple[QualityScoreRow]]:
        """The scores, for a page: by scope, level, column, area, thing."""
        f = filters
        statement = self.select(QualityScoreRow)
        for column, value in (
            (QualityScoreRow.scope, f.scope),
            (QualityScoreRow.level, f.level),
            (QualityScoreRow.column, f.column),
            (QualityScoreRow.subject_id, f.subject_id),
        ):
            if value is not None:
                statement = statement.where(column == value)
        if f.area is not None:
            statement = statement.where(QualityScoreRow.areas.contains([f.area]))
        return statement

    async def score(self, key: str) -> QualityScoreRow | None:
        found = await self._session.execute(
            self.select(QualityScoreRow).where(QualityScoreRow.key == key)
        )
        return found.scalar_one_or_none()

    async def areas(self) -> Sequence[QualityScoreRow]:
        """The areas' scores: the workspace, its columns, teams, applications."""
        found = await self._session.execute(
            self.select(QualityScoreRow)
            .where(QualityScoreRow.scope != "entity")
            .order_by(QualityScoreRow.scope, QualityScoreRow.score, QualityScoreRow.subject_name)
        )
        return found.scalars().all()

    async def levels(self) -> dict[str, int]:
        """The things measured, by level."""
        found = await self._session.execute(
            select(QualityScoreRow.level, func.count())
            .where(
                QualityScoreRow.workspace_id == self.workspace_id,
                QualityScoreRow.scope == "entity",
            )
            .group_by(QualityScoreRow.level)
        )
        return dict(found.tuples().all())

    async def weakest(self, limit: int) -> Sequence[QualityScoreRow]:
        """The things known least well, in an order that holds."""
        found = await self._session.execute(
            self.select(QualityScoreRow)
            .where(QualityScoreRow.scope == "entity")
            .order_by(QualityScoreRow.score, QualityScoreRow.subject_name, QualityScoreRow.id)
            .limit(limit)
        )
        return found.scalars().all()

    async def of_subjects(self, ids: Sequence[uuid.UUID]) -> Sequence[QualityScoreRow]:
        if not ids:
            return []
        found = await self._session.execute(
            self.select(QualityScoreRow).where(
                QualityScoreRow.scope == "entity", QualityScoreRow.subject_id.in_(list(ids))
            )
        )
        return found.scalars().all()

    def add_point(self, point: QualityPoint) -> None:
        self.add(point)

    async def moves(self, *, since: datetime) -> list[tuple[QualityScoreRow, QualityPoint]]:
        """Each area's score as it stands — the workspace, its columns,
        teams, applications — and the point it stood at `since`, when it
        was measured by then (LEKA-383)."""
        areas = await self.areas()
        if not areas:
            return []
        then = await self._session.execute(
            self.select(QualityPoint)
            .where(
                QualityPoint.key.in_([row.key for row in areas]),
                QualityPoint.measured_at <= since,
            )
            .distinct(QualityPoint.key)
            .order_by(QualityPoint.key, QualityPoint.measured_at.desc(), QualityPoint.id)
        )
        points = {point.key: point for point in then.scalars().all()}
        return [(row, points[row.key]) for row in areas if row.key in points]

    async def history(self, key: str, *, since: datetime) -> Sequence[QualityPoint]:
        """A score's changes since a date, the oldest first — and the point
        it stood at then, so a series starts where it was."""
        before = await self._session.execute(
            self.select(QualityPoint)
            .where(QualityPoint.key == key, QualityPoint.measured_at < since)
            .order_by(QualityPoint.measured_at.desc(), QualityPoint.id)
            .limit(1)
        )
        after = await self._session.execute(
            self.select(QualityPoint)
            .where(QualityPoint.key == key, QualityPoint.measured_at >= since)
            .order_by(QualityPoint.measured_at, QualityPoint.id)
        )
        return [*before.scalars().all(), *after.scalars().all()]


# ── the activity (LEKA-383) ──────────────────────────────────────────────────


class ActivityRepository(WorkspaceScopedRepository):
    """What LEKA did, and what people decided, over a period: its analyses,
    what they raised and proposed, the decisions taken — for Activité."""

    async def runs_between(self, *, since: datetime, until: datetime) -> Sequence[IntelligenceRun]:
        """The analyses that finished between two dates and did their work."""
        return await self.list(
            self.select(IntelligenceRun).where(
                IntelligenceRun.finished_at >= since,
                IntelligenceRun.finished_at < until,
                IntelligenceRun.status.in_(("succeeded", "partial")),
            )
        )

    async def findings_between(
        self, *, since: datetime, until: datetime, limit: int
    ) -> Sequence[Finding]:
        """The findings first raised between two dates."""
        return await self.list(
            self.select(Finding)
            .where(Finding.first_seen_at >= since, Finding.first_seen_at < until)
            .order_by(Finding.first_seen_at.desc(), Finding.id)
            .limit(limit)
        )

    async def candidates_between(
        self, *, since: datetime, until: datetime, limit: int
    ) -> Sequence[EnrichmentCandidate]:
        """The proposals first made, or decided, between two dates."""
        return await self.list(
            self.select(EnrichmentCandidate)
            .where(
                or_(
                    and_(
                        EnrichmentCandidate.first_seen_at >= since,
                        EnrichmentCandidate.first_seen_at < until,
                    ),
                    and_(
                        EnrichmentCandidate.decided_at >= since,
                        EnrichmentCandidate.decided_at < until,
                    ),
                )
            )
            .order_by(EnrichmentCandidate.first_seen_at.desc(), EnrichmentCandidate.id)
            .limit(limit)
        )

    async def conflicts_between(
        self, *, since: datetime, until: datetime, limit: int
    ) -> Sequence[KnowledgeConflict]:
        """The conflicts first found — or decided on — between two dates:
        touched since, at least."""
        return await self.list(
            self.select(KnowledgeConflict)
            .where(KnowledgeConflict.updated_at >= since, KnowledgeConflict.first_seen_at < until)
            .order_by(KnowledgeConflict.first_seen_at.desc(), KnowledgeConflict.id)
            .limit(limit)
        )

    async def source_events_between(
        self, *, since: datetime, until: datetime, limit: int
    ) -> list[tuple[SourceEvent, Source | None]]:
        """What happened to the sources between two dates — each with its
        source, unless deleted since."""
        rows = await self._session.execute(
            select(SourceEvent, Source)
            .outerjoin(
                Source,
                and_(Source.id == SourceEvent.source_id, Source.workspace_id == self.workspace_id),
            )
            .where(
                SourceEvent.workspace_id == self.workspace_id,
                SourceEvent.created_at >= since,
                SourceEvent.created_at < until,
            )
            .order_by(SourceEvent.created_at.desc(), SourceEvent.id)
            .limit(limit)
        )
        return [(event, source) for event, source in rows.tuples().all()]

    async def waiting(self) -> int:
        """What waits on someone in À valider: the proposals and the open
        conflicts."""
        proposed = await self._session.scalar(
            select(func.count()).where(
                EnrichmentCandidate.workspace_id == self.workspace_id,
                EnrichmentCandidate.status == "proposed",
            )
        )
        open_ = await self._session.scalar(
            select(func.count()).where(
                KnowledgeConflict.workspace_id == self.workspace_id,
                KnowledgeConflict.status == "open",
            )
        )
        return int(proposed or 0) + int(open_ or 0)

    async def people(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str | None]]:
        """These people, as the workspace knows them: their name — their
        address when they gave none — and their role here."""
        if not ids:
            return {}
        rows = await self._session.execute(
            select(User.id, User.first_name, User.last_name, User.email, Membership.role)
            .outerjoin(
                Membership,
                and_(Membership.user_id == User.id, Membership.workspace_id == self.workspace_id),
            )
            .where(User.id.in_(set(ids)))
        )
        return {
            user: (
                " ".join(part for part in (first, last) if part) or email,
                role.value if role is not None else None,
            )
            for user, first, last, email, role in rows.tuples().all()
        }
