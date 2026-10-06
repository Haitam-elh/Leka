"""The intelligence engine (LEKA-377): a run, its analyses, their findings.

    start      a run, recorded `running` before anything is read: a run a
               worker dies in is found and said abandoned
    read_*     what its analyses read, once — the company model as the
               architecture reads it, the contexts in use. The job reads
               each part in its own session: a part that cannot be read is
               None, the analyses that need it are skipped, the others run
    record     one analysis's outcome: its step, and — when it succeeded —
               its findings kept: new ones opened, those seen again
               updated, those no longer seen resolved, those seen once more
               reopened. A failed analysis resolves nothing
    finish     the run's status from its steps — succeeded, partial when
               some failed, failed when none succeeded — and its counts

The job (job.py) holds the transactions: the run is committed first, each
step in its own, so one analysis's failure — even to be written — is never
another's. Everything else here reads: the catalogue, the runs, the
findings, the summary a product surface shows, and what LEKA concluded
about given things, for the services downstream.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from leka.connectors import manifests
from leka.context import Context, ContextRepository
from leka.intelligence.analysis import (
    Analyzer,
    ContextStanding,
    Draft,
    Material,
    Method,
    Outcome,
    catalogue_hash,
)
from leka.intelligence.changes import (
    AFTER,
    HISTORY,
    Impacted,
    current,
    impacts,
    signals,
    significance,
)
from leka.intelligence.curation import propose
from leka.intelligence.models import Finding, IntelligenceRun, IntelligenceStep
from leka.intelligence.repository import IntelligenceRepository
from leka.intelligence.rules import ANALYZERS
from leka.intelligence.schemas import (
    AnalyzerRead,
    ChangeImpactDetail,
    ChangeImpactRead,
    ChangeImpactTimeline,
    EvidenceRead,
    FindingDetail,
    FindingRead,
    FollowedRead,
    ImpactRead,
    IntelligenceSummary,
    RunDetail,
    RunRead,
    StepRead,
    SubjectRead,
)
from leka.knowledge import (
    ArchitectureRead,
    AssertionRepository,
    ChangeFootprint,
    EntityBrief,
    EntityStanding,
    GraphService,
)

logger = structlog.get_logger(__name__)

# The contexts a run reads: those used in the last month, the latest first.
CONTEXT_WINDOW = timedelta(days=30)
MAX_CONTEXTS = 500
# What a summary names.
TOP = 5
# The changes a run reads: the last HISTORY's, at most this many.
MAX_CHANGES = 100


@dataclass(frozen=True)
class ModelRead:
    """The model part of a run's material, read in one session."""

    architecture: ArchitectureRead
    owners: dict[uuid.UUID, tuple[str, ...]]
    standing: dict[uuid.UUID, EntityStanding]
    documents: int
    categories: dict[str, str]
    owned_by: dict[uuid.UUID, tuple[EntityBrief, ...]]
    memberships: dict[uuid.UUID, tuple[EntityBrief, ...]]


class UnknownAnalyzerError(ValueError):
    """An analysis asked for by a name LEKA does not have."""

    def __init__(self, names: Sequence[str]) -> None:
        super().__init__(", ".join(names))
        self.names = list(names)


class IntelligenceService:
    def __init__(
        self,
        repository: IntelligenceRepository,
        graph: GraphService,
        contexts: ContextRepository,
        *,
        analyzers: Sequence[Analyzer] = ANALYZERS,
        assertions: AssertionRepository | None = None,
    ) -> None:
        self._repository = repository
        self._graph = graph
        self._contexts = contexts
        self._analyzers = tuple(analyzers)
        # Where the policy's acceptances are kept (LEKA-380): none, none made.
        self._assertions = assertions

    # ── the catalogue ──────────────────────────────────────────────────

    def catalogue(self) -> list[AnalyzerRead]:
        return [
            AnalyzerRead(
                name=analyzer.name,
                version=analyzer.version,
                category=analyzer.category,
                method=analyzer.method.value,
                reads=sorted(reads.value for reads in analyzer.reads),
                summary=analyzer.summary,
                available=analyzer.method is Method.RULES,
            )
            for analyzer in self._analyzers
        ]

    def chosen(self, names: Sequence[str] | None) -> tuple[Analyzer, ...]:
        """The analyses a run makes: every one, or those named — an unknown
        name refused rather than ignored."""
        if not names:
            return self._analyzers
        known = {analyzer.name: analyzer for analyzer in self._analyzers}
        unknown = [name for name in names if name not in known]
        if unknown:
            raise UnknownAnalyzerError(unknown)
        wanted = set(names)
        return tuple(analyzer for analyzer in self._analyzers if analyzer.name in wanted)

    def fingerprint(self) -> str:
        return catalogue_hash(self._analyzers)

    # ── a run ──────────────────────────────────────────────────────────

    async def start(
        self,
        *,
        trigger: str,
        requested: Sequence[str],
        by: uuid.UUID | None,
        job_run_id: uuid.UUID | None,
        now: datetime,
    ) -> IntelligenceRun:
        run = IntelligenceRun(
            workspace_id=self._repository.workspace_id,
            status="running",
            trigger=trigger,
            requested_by=by,
            requested=list(requested),
            started_at=now,
            model_built_at=await self._graph.built_at(),
            catalogue=self.fingerprint(),
            job_run_id=job_run_id,
            counts={},
        )
        self._repository.add_run(run)
        return run

    async def read_model(self, *, now: datetime) -> ModelRead:
        """The company model, as the architecture reads it — every card —
        who owns each card's entity, team or person, what the model holds
        around each (LEKA-379), how many documents there are, the family of
        each kind of source, and the teams of the people who maintain them
        (LEKA-380)."""
        architecture = await self._graph.architecture(now=now, environment=None, detailed=True)
        ids = [card.entity_id for card in architecture.cards if card.entity_id is not None]
        owners = await self._graph.owners(ids)
        people = list({person.id for card in architecture.cards for person in card.maintainers})
        teams = await self._graph.memberships(people)
        return ModelRead(
            architecture=architecture,
            owners={
                entity: tuple(brief.name for brief in briefs) for entity, briefs in owners.items()
            },
            standing=await self._graph.standing(ids),
            documents=await self._graph.documents(),
            categories={manifest.key.value: manifest.category.value for manifest in manifests()},
            owned_by={entity: tuple(briefs) for entity, briefs in owners.items()},
            memberships={person: tuple(found) for person, found in teams.items()},
        )

    async def read_contexts(self, *, now: datetime) -> tuple[ContextStanding, ...]:
        """Where the contexts used in the last month stand."""
        rows = await self._contexts.standing(used_since=now - CONTEXT_WINDOW, limit=MAX_CONTEXTS)
        return tuple(_standing(context, quality) for context, quality in rows)

    async def read_changes(self, *, now: datetime) -> tuple[ChangeFootprint, ...]:
        """The changes of the last HISTORY, each with its footprint (LEKA-378)."""
        found, _ = await self._graph.footprints(
            since=now - HISTORY, until=now, limit=MAX_CHANGES, after=AFTER
        )
        return tuple(found)

    async def record(
        self,
        run_id: uuid.UUID,
        analyzer: Analyzer,
        outcome: Outcome,
        material: Material,
        *,
        now: datetime,
    ) -> IntelligenceStep:
        """One analysis's outcome: its step, its findings kept — and its
        proposals, as candidates (LEKA-380)."""
        counts = {"found": len(outcome.drafts)}
        if outcome.proposals:
            counts["proposals"] = len(outcome.proposals)
        if outcome.status == "succeeded":
            counts |= await self._apply(run_id, analyzer, outcome.drafts, material, now=now)
            if analyzer.category == "enrichment":
                counts |= await propose(
                    self._repository,
                    self._assertions,
                    run_id,
                    analyzer,
                    outcome.proposals,
                    material,
                    now=now,
                )
        step = IntelligenceStep(
            workspace_id=self._repository.workspace_id,
            run_id=run_id,
            analyzer=analyzer.name,
            version=analyzer.version,
            status=outcome.status,
            started_at=now,
            duration_ms=outcome.duration_ms,
            counts=counts,
            error=outcome.error,
            reason=outcome.reason,
        )
        self._repository.add_step(step)
        if outcome.status in ("failed", "timed_out"):
            logger.warning(
                "intelligence_step_failed",
                run=str(run_id),
                analyzer=analyzer.name,
                status=outcome.status,
                error=outcome.error,
                duration_ms=outcome.duration_ms,
            )
        return step

    async def record_failure(
        self, run_id: uuid.UUID, analyzer: Analyzer, error: str, *, now: datetime
    ) -> None:
        """An analysis whose outcome could not be kept: its step, failed."""
        self._repository.add_step(
            IntelligenceStep(
                workspace_id=self._repository.workspace_id,
                run_id=run_id,
                analyzer=analyzer.name,
                version=analyzer.version,
                status="failed",
                started_at=now,
                duration_ms=0,
                counts={},
                error=error[:200],
            )
        )

    async def finish(
        self, run_id: uuid.UUID, *, now: datetime, error: str | None = None
    ) -> RunRead:
        run = await self._repository.run(run_id)
        if run is None:
            msg = f"No intelligence run {run_id}"
            raise LookupError(msg)
        steps = await self._repository.steps(run_id)
        states = Counter(step.status for step in steps)
        broken = states["failed"] + states["timed_out"]
        if error is not None or (broken and not states["succeeded"] and not states["skipped"]):
            run.status = "failed"
        elif broken:
            run.status = "partial"
        else:
            run.status = "succeeded"
        totals: Counter[str] = Counter()
        for step in steps:
            totals.update({key: int(value) for key, value in step.counts.items()})
        run.counts = dict(totals) | {f"steps_{state}": n for state, n in states.items()}
        run.finished_at = now
        run.error = error[:200] if error else None
        logger.info("intelligence_run_finished", run=str(run_id), status=run.status, **run.counts)
        return RunRead.model_validate(run)

    async def _apply(
        self,
        run_id: uuid.UUID,
        analyzer: Analyzer,
        drafts: Sequence[Draft],
        material: Material,
        *,
        now: datetime,
    ) -> dict[str, int]:
        kept = await self._repository.of_analyzer(analyzer.name)
        counts = {"opened": 0, "seen": 0, "resolved": 0, "reopened": 0}
        said: set[str] = set()
        for draft in drafts:
            said.add(draft.key)
            finding = kept.get(draft.key)
            if finding is None:
                finding = Finding(
                    workspace_id=self._repository.workspace_id,
                    analyzer=analyzer.name,
                    key=draft.key,
                    status="open",
                    first_seen_at=now,
                    first_run_id=run_id,
                    occurrences=0,
                    reopened=0,
                )
                self._repository.add_finding(finding)
                counts["opened"] += 1
            elif finding.status == "resolved":
                finding.status = "open"
                finding.resolved_at = None
                finding.resolved_run_id = None
                finding.reopened += 1
                counts["reopened"] += 1
            else:
                counts["seen"] += 1
            _write(finding, draft, analyzer, material, run_id=run_id, now=now)
        for key, finding in kept.items():
            if finding.status == "open" and key not in said:
                finding.status = "resolved"
                finding.resolved_at = now
                finding.resolved_run_id = run_id
                counts["resolved"] += 1
        return counts

    # ── reads ──────────────────────────────────────────────────────────

    @staticmethod
    def run_read(run: IntelligenceRun) -> RunRead:
        return RunRead.model_validate(run)

    @staticmethod
    def run_reads(runs: Sequence[IntelligenceRun]) -> list[RunRead]:
        return [RunRead.model_validate(run) for run in runs]

    async def run_detail(self, run_id: uuid.UUID) -> RunDetail | None:
        run = await self._repository.run(run_id)
        if run is None:
            return None
        steps = await self._repository.steps(run_id)
        return RunDetail(
            **RunRead.model_validate(run).model_dump(),
            steps=[StepRead.model_validate(step) for step in steps],
        )

    @staticmethod
    def finding_read(finding: Finding) -> FindingRead:
        return FindingRead.model_validate(
            {
                "id": finding.id,
                "analyzer": finding.analyzer,
                "analyzer_version": finding.analyzer_version,
                "category": finding.category,
                "code": finding.code,
                "params": finding.params,
                "statement": finding.statement,
                "severity": finding.severity,
                "rank": finding.rank,
                "confidence": finding.confidence,
                "subject": {
                    "type": finding.subject_type,
                    "id": finding.subject_id,
                    "name": finding.subject_name,
                    "kind": finding.subject_kind,
                },
                "status": finding.status,
                "first_seen_at": finding.first_seen_at,
                "last_seen_at": finding.last_seen_at,
                "resolved_at": finding.resolved_at,
                "occurrences": finding.occurrences,
            }
        )

    @classmethod
    def finding_reads(cls, findings: Sequence[Finding]) -> list[FindingRead]:
        return [cls.finding_read(finding) for finding in findings]

    async def finding_detail(self, finding_id: uuid.UUID) -> FindingDetail | None:
        finding = await self._repository.finding(finding_id)
        if finding is None:
            return None
        return FindingDetail(
            **self.finding_read(finding).model_dump(),
            related=[SubjectRead.model_validate(subject) for subject in finding.related],
            evidence=[EvidenceRead.model_validate(item) for item in finding.evidence],
            provenance=finding.provenance,
            first_run_id=finding.first_run_id,
            last_run_id=finding.last_run_id,
            resolved_run_id=finding.resolved_run_id,
            reopened=finding.reopened,
        )

    async def summary(self) -> IntelligenceSummary:
        counts = await self._repository.open_counts()
        latest = await self._repository.latest_run()
        return IntelligenceSummary(
            open={severity: counts.get(severity, 0) for severity in ("high", "medium", "low")},
            top=self.finding_reads(await self._repository.top(TOP)),
            latest=RunRead.model_validate(latest) if latest else None,
        )

    async def change_timeline(
        self,
        *,
        now: datetime,
        since: datetime,
        until: datetime,
        around: uuid.UUID | None,
        limit: int,
    ) -> ChangeImpactTimeline:
        """The changes between two dates, judged — around an entity: those
        made to it, to what it is made of, or to what it depends on."""
        found, truncated = await self._graph.footprints(
            since=since, until=until, limit=limit, after=AFTER, around=around
        )
        return ChangeImpactTimeline(
            since=since,
            until=until,
            around=around,
            changes=[_change_read(footprint, now) for footprint in found],
            truncated=truncated,
        )

    async def change_detail(
        self, change_id: uuid.UUID, *, now: datetime
    ) -> ChangeImpactDetail | None:
        """One change: everything it reaches, ranked, the business holding
        it, what followed, what its source says of it."""
        footprint = await self._graph.footprint(change_id, after=AFTER)
        if footprint is None:
            return None
        return ChangeImpactDetail(
            **_change_read(footprint, now).model_dump(),
            details=footprint.details,
            source_ids=footprint.source_ids,
            impacts=[_impact_read(item) for item in impacts(footprint)],
            applications=[_subject(entity) for entity in footprint.applications],
            capabilities=[_subject(tie.entity) for tie in footprint.capabilities],
            processes=[_subject(tie.entity) for tie in footprint.processes],
            followed=[
                FollowedRead(
                    subject=_subject(incident.entity),
                    opened_at=incident.opened_at,
                    hours_after=(
                        round((incident.opened_at - footprint.at).total_seconds() / 3600, 1)
                        if incident.opened_at
                        else None
                    ),
                    severity=incident.severity,
                    state=incident.state,
                    on=_subject(incident.on) if incident.on else None,
                    stated=incident.stated,
                )
                for incident in footprint.incidents
            ],
        )

    async def about(self, ids: Sequence[uuid.UUID], *, limit: int = 20) -> list[FindingRead]:
        """What LEKA concluded, and still holds, about these things — for a
        service downstream (an intention, a context) to start from."""
        return self.finding_reads(await self._repository.about(ids, limit=limit))


def _subject(entity: EntityBrief) -> SubjectRead:
    return SubjectRead(type="entity", id=entity.id, name=entity.name, kind=entity.type.value)


def _impact_read(item: Impacted) -> ImpactRead:
    return ImpactRead(
        subject=SubjectRead.model_validate(item.subject.as_dict()),
        distance=item.distance,
        score=item.score,
        reasons=list(item.reasons),
    )


def _change_read(footprint: ChangeFootprint, now: datetime) -> ChangeImpactRead:
    ranked = impacts(footprint)
    return ChangeImpactRead.model_validate(
        {
            "id": footprint.change.id,
            "name": footprint.change.name,
            "kind": footprint.kind,
            "at": footprint.at,
            "state": footprint.state,
            "environment": footprint.environment,
            "current": current(footprint, now),
            "significance": significance(footprint),
            "signals": list(signals(footprint)),
            "touched": [_subject(touch.entity) for touch in footprint.touched],
            "reached": len(ranked),
            "incidents": len(footprint.incidents),
            "top": [_impact_read(item) for item in ranked[:3]],
            "sources": footprint.sources,
        }
    )


def _standing(context: Context, quality: dict[str, object] | None) -> ContextStanding:
    level = quality.get("level") if quality else None
    score = quality.get("score") if quality else None
    return ContextStanding(
        id=context.id,
        title=context.title,
        status=context.status,
        follow=context.follow,
        version=context.current_version,
        used_at=context.used_at,
        stale_since=context.stale_since,
        pending=context.pending_count,
        level=level if isinstance(level, str) else None,
        score=float(score) if isinstance(score, int | float) else None,
    )


def _write(
    finding: Finding,
    draft: Draft,
    analyzer: Analyzer,
    material: Material,
    *,
    run_id: uuid.UUID,
    now: datetime,
) -> None:
    """What a finding says, as this run saw it."""
    finding.analyzer_version = analyzer.version
    finding.category = analyzer.category
    finding.code = draft.code
    finding.params = dict(draft.params)
    finding.statement = draft.statement
    finding.severity = draft.severity.value
    finding.rank = draft.rank
    finding.confidence = round(max(0.0, min(draft.confidence, 1.0)), 4)
    finding.subject_type = draft.subject.type
    finding.subject_id = draft.subject.id
    finding.subject_name = draft.subject.name[:500]
    finding.subject_kind = draft.subject.kind
    finding.related = [subject.as_dict() for subject in draft.related]
    finding.evidence = [item.as_dict() for item in draft.evidence]
    finding.provenance = {
        "analyzer": analyzer.name,
        "version": analyzer.version,
        "method": analyzer.method.value,
        "run_id": str(run_id),
        "model_built_at": material.built_at.isoformat() if material.built_at else None,
        "sources": list(draft.sources),
        "context_version": draft.context_version,
    }
    finding.last_seen_at = now
    finding.last_run_id = run_id
    finding.occurrences += 1
