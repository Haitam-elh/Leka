"""Database access for the intelligence module (LEKA-377).

The only place in this module where a query is written (architecture rule
4). What a run reads of the company model and the contexts goes through
leka.knowledge and leka.context; this reads and writes the runs, their
steps and the findings.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.db import WorkspaceScopedRepository
from leka.intelligence.models import Finding, IntelligenceRun, IntelligenceStep
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
        """Findings resolved before `before`: what was true long ago."""
        result = await self._session.execute(
            delete(Finding)
            .where(Finding.status == "resolved", Finding.resolved_at < before)
            .execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)
