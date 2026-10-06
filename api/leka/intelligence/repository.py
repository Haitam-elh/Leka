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

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import Source
from leka.db import WorkspaceScopedRepository
from leka.intelligence.models import (
    AuthorityRule,
    EnrichmentCandidate,
    Finding,
    IntelligenceRun,
    IntelligenceStep,
    KnowledgeConflict,
)
from leka.knowledge import ModelRun

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
