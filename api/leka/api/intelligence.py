"""The intelligence engine (LEKA-377): what LEKA concludes, and how it got there.

    GET  /intelligence/analyzers         the analyses LEKA runs: what each
                                         reads, how it reasons, its version
    POST /intelligence/runs              analyse now — every analysis, or
                                         those named; 202, `queued` false when
                                         a run is already on its way
    GET  /intelligence/runs              the runs, the latest first: why, from
                                         which build, what came of them
    GET  /intelligence/runs/{id}         one, with what each analysis did — or
                                         why it failed, timed out, was skipped
    GET  /intelligence/findings          the findings, the most pressing first
                                         — by state, severity, category,
                                         analysis, what they are about
    GET  /intelligence/findings/{id}     one: what shows it, where that was
                                         read, which runs saw it
    GET  /intelligence/summary           what is open, how bad, the most
                                         pressing, the latest run — for a
                                         product surface at a glance
    GET  /intelligence/changes           the changes between two dates, the
                                         latest first, judged (LEKA-378):
                                         current or history, how much they
                                         matter and why, what they reach —
                                         around an entity, or everywhere
    GET  /intelligence/changes/{id}      one change: everything it reaches,
                                         ranked, the business holding it,
                                         the incidents that followed

    GET  /intelligence/enrichment/candidates       the enrichments of the
                                         company model proposed (LEKA-380) —
                                         by state, family, analysis, thing
    GET  /intelligence/enrichment/candidates/{id}  one: what shows it, where
                                         that was read, every decision
    GET  /intelligence/enrichment/summary          how many wait, were
                                         accepted, rejected, withdrawn
    POST .../candidates/{id}/accept      validated: kept as a fact, applied
                                         by the next build of the model
    POST .../candidates/{id}/reject      never again — and, accepted,
                                         withdrawn from the model
    POST .../candidates/{id}/reprocess   back to its analysis, now

Read by every member (`workspace:read`), like the company model they are
drawn from. Asking for a run is asking LEKA something, like an intention:
`intention:create`, refused to a suspended workspace. Deciding what goes
into the company model is approving: `intention:approve`, as À valider
is — an admin's. A route validates,
calls one service, and returns (architecture rule 6); the workspace is the
session's (rule 3): another workspace's run or finding is 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.context import ContextRepository
from leka.core.errors import ErrorCode
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission
from leka.intelligence import (
    AnalysisRequest,
    AnalysisRequested,
    AnalyzerRead,
    CandidateDetail,
    CandidateFilters,
    CandidateRead,
    ChangeImpactDetail,
    ChangeImpactTimeline,
    Decision,
    DecisionRefusedError,
    EnrichmentCandidate,
    EnrichmentService,
    EnrichmentSummary,
    Finding,
    FindingDetail,
    FindingFilters,
    FindingRead,
    IntelligenceRepository,
    IntelligenceRun,
    IntelligenceService,
    IntelligenceSummary,
    Reprocessed,
    RunDetail,
    RunRead,
    UnknownAnalyzerError,
    candidate_detail,
    candidate_read,
    candidate_reads,
)
from leka.intelligence.job import queue_run
from leka.knowledge import (
    AssertionRepository,
    EntityRepository,
    GraphRepository,
    GraphService,
    queue_model_build,
)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Asker = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]

RUN_SORTS = SortCatalogue(
    fields=(
        SortableField(
            "started_at", IntelligenceRun.started_at, "ix_intelligence_runs_workspace_started_at"
        ),
    ),
    default="started_at",
)
FINDING_SORTS = SortCatalogue(
    fields=(
        SortableField("rank", Finding.rank, "ix_intelligence_findings_workspace_rank"),
        SortableField(
            "last_seen_at", Finding.last_seen_at, "ix_intelligence_findings_workspace_seen"
        ),
    ),
    default="rank",
)
CANDIDATE_SORTS = SortCatalogue(
    fields=(
        SortableField(
            "last_seen_at",
            EnrichmentCandidate.last_seen_at,
            "ix_enrichment_candidates_workspace_seen",
        ),
        SortableField(
            "confidence", EnrichmentCandidate.confidence, "a sort in memory: a few hundred at most"
        ),
    ),
    default="last_seen_at",
)


def _service(session: SessionDep, principal: Reader) -> IntelligenceService:
    return IntelligenceService(
        IntelligenceRepository(session, principal.workspace_id),
        GraphService(GraphRepository(session, principal.workspace_id)),
        ContextRepository(session, principal.workspace_id),
    )


Reading = Annotated[IntelligenceService, Depends(_service)]


def _missing(what: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"No such {what}.")


@router.get("/analyzers", response_model=list[AnalyzerRead])
async def analyzers(service: Reading) -> list[AnalyzerRead]:
    """The analyses LEKA runs: what each reads, how it reasons, its version,
    whether it can run here — a model-assisted one waits for the model
    gateway."""
    return service.catalogue()


@router.post("/runs", response_model=AnalysisRequested, status_code=status.HTTP_202_ACCEPTED)
async def request_run(
    body: AnalysisRequest, service: Reading, principal: Asker
) -> AnalysisRequested:
    """Analyse now: every analysis, or those named — an unknown name is 422.
    One run at a time per workspace: `queued` is false when one is already
    on its way, and it will be the one that answers."""
    try:
        service.chosen(body.analyzers)
    except UnknownAnalyzerError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            f"No such analysis: {', '.join(error.names)}.",
        ) from error
    queued = await queue_run(
        principal.workspace_id,
        trigger="request",
        by=principal.user_id,
        analyzers=body.analyzers or (),
    )
    return AnalysisRequested(queued=queued)


@router.get("/runs", response_model=PageEnvelope[RunRead])
async def runs(session: SessionDep, principal: Reader, page: PageParams) -> PageEnvelope[RunRead]:
    """The runs, the latest first: why each ran, from which build of the
    model, what came of it."""
    repository = IntelligenceRepository(session, principal.workspace_id)
    result = await serve_page(
        session, repository.runs(), request=page, catalogue=RUN_SORTS, id_column=IntelligenceRun.id
    )
    return PageEnvelope(
        data=IntelligenceService.run_reads(result.items), next_cursor=result.next_cursor
    )


@router.get("/runs/{run_id}", response_model=RunDetail)
async def run(run_id: uuid.UUID, service: Reading) -> RunDetail:
    """One run, with what each analysis did: found what, opened, resolved —
    or failed, timed out, was skipped, and why."""
    found = await service.run_detail(run_id)
    if found is None:
        raise _missing("run")
    return found


@router.get("/findings", response_model=PageEnvelope[FindingRead])
async def findings(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    state: Annotated[
        Literal["open", "resolved"] | None,
        Query(alias="status", description="Open or resolved; none: both."),
    ] = None,
    severity: Annotated[Literal["high", "medium", "low"] | None, Query()] = None,
    category: Annotated[str | None, Query(max_length=30)] = None,
    analyzer: Annotated[str | None, Query(max_length=60)] = None,
    subject: Annotated[
        uuid.UUID | None, Query(description="About this entity, context or source.")
    ] = None,
) -> PageEnvelope[FindingRead]:
    """The findings, the most pressing first (`sort=rank`, the default) or
    the latest seen (`sort=last_seen_at`)."""
    repository = IntelligenceRepository(session, principal.workspace_id)
    statement = repository.findings(
        FindingFilters(
            status=state,
            severity=severity,
            category=category,
            analyzer=analyzer,
            subject_id=subject,
        )
    )
    result = await serve_page(
        session, statement, request=page, catalogue=FINDING_SORTS, id_column=Finding.id
    )
    return PageEnvelope(
        data=IntelligenceService.finding_reads(result.items), next_cursor=result.next_cursor
    )


@router.get("/findings/{finding_id}", response_model=FindingDetail)
async def finding(finding_id: uuid.UUID, service: Reading) -> FindingDetail:
    """One finding: what shows it, where that was read — the build of the
    model, the sources, the context version, the analysis and its version —
    and which runs first saw it, last saw it, resolved it."""
    found = await service.finding_detail(finding_id)
    if found is None:
        raise _missing("finding")
    return found


@router.get("/summary", response_model=IntelligenceSummary)
async def summary(service: Reading) -> IntelligenceSummary:
    """What is open, by severity; the most pressing; the latest run."""
    return await service.summary()


# ── change and impact (LEKA-378) ───────────────────────────────────────

# A timeline's window when none is asked, and at most.
CHANGE_WINDOW = timedelta(days=30)
MAX_CHANGE_WINDOW = timedelta(days=90)


@router.get("/changes", response_model=ChangeImpactTimeline)
async def changes(
    service: Reading,
    since: Annotated[
        datetime | None, Query(description="From; 30 days before `until` when not given.")
    ] = None,
    until: Annotated[datetime | None, Query(description="To; now when not given.")] = None,
    entity: Annotated[
        uuid.UUID | None,
        Query(description="Made to it, to what it is made of, or to what it depends on."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> ChangeImpactTimeline:
    """The changes between two dates — deployments, change requests,
    releases, pull requests — the latest first, each judged: current
    (within 72 hours) or history, how much it matters and why, what it was
    made to, how far it reaches, the incidents that followed. 90 days at
    most."""
    now = datetime.now(UTC)
    end = until or now
    start = since or end - CHANGE_WINDOW
    if start >= end or end - start > MAX_CHANGE_WINDOW:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "`since` must come before `until`, at most 90 days before.",
        )
    return await service.change_timeline(
        now=now, since=start, until=end, around=entity, limit=limit
    )


@router.get("/changes/{change_id}", response_model=ChangeImpactDetail)
async def change(change_id: uuid.UUID, service: Reading) -> ChangeImpactDetail:
    """One change: everything it reaches, the most affected first — what
    an incident hit, what it was made to, what depends on that — the
    applications and the business holding it, the incidents that followed
    or that its source says it caused, and what its source says of it."""
    found = await service.change_detail(change_id, now=datetime.now(UTC))
    if found is None:
        raise _missing("change")
    return found


# ── enrichment (LEKA-380) ──────────────────────────────────────────────


def _enrichment(session: SessionDep, principal: Reader) -> EnrichmentService:
    return EnrichmentService(
        IntelligenceRepository(session, principal.workspace_id),
        AssertionRepository(session, principal.workspace_id),
        EntityRepository(session, principal.workspace_id),
    )


Curating = Annotated[EnrichmentService, Depends(_enrichment)]


def _refused(error: DecisionRefusedError) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, error.detail)


@router.get("/enrichment/candidates", response_model=PageEnvelope[CandidateRead])
async def candidates(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    state: Annotated[
        Literal["proposed", "accepted", "rejected", "withdrawn"] | None,
        Query(alias="status", description="Where it stands; none: all."),
    ] = None,
    family: Annotated[
        Literal["relationship", "semantic", "organisation", "business"] | None, Query()
    ] = None,
    analyzer: Annotated[str | None, Query(max_length=60)] = None,
    subject: Annotated[
        uuid.UUID | None, Query(description="Enriching this entity, or joining it to another.")
    ] = None,
) -> PageEnvelope[CandidateRead]:
    """The enrichments of the company model proposed, the latest seen
    first (`sort=last_seen_at`, the default) or the surest
    (`sort=confidence`)."""
    repository = IntelligenceRepository(session, principal.workspace_id)
    statement = repository.candidates(
        CandidateFilters(status=state, family=family, analyzer=analyzer, subject_id=subject)
    )
    result = await serve_page(
        session,
        statement,
        request=page,
        catalogue=CANDIDATE_SORTS,
        id_column=EnrichmentCandidate.id,
    )
    return PageEnvelope(data=candidate_reads(result.items), next_cursor=result.next_cursor)


@router.get("/enrichment/summary", response_model=EnrichmentSummary)
async def enrichment_summary(service: Curating) -> EnrichmentSummary:
    """How many wait, by family; how many were accepted — by the policy
    among them — rejected, withdrawn."""
    return await service.summary()


@router.get("/enrichment/candidates/{candidate_id}", response_model=CandidateDetail)
async def candidate(
    candidate_id: uuid.UUID, session: SessionDep, principal: Reader
) -> CandidateDetail:
    """One candidate: what it proposes, what shows it, where that was read,
    every decision taken on it."""
    found = await IntelligenceRepository(session, principal.workspace_id).candidate(candidate_id)
    if found is None:
        raise _missing("candidate")
    return candidate_detail(found)


@router.post("/enrichment/candidates/{candidate_id}/accept", response_model=CandidateDetail)
async def accept(
    candidate_id: uuid.UUID,
    body: Decision,
    session: SessionDep,
    service: Curating,
    principal: Approver,
) -> CandidateDetail:
    """Validated: kept as a fact of the company model, applied by its next
    build — queued now. 409 when it is no longer proposed, when what it is
    about has gone, or when it replaces what a source says and `override`
    does not say so."""
    try:
        found = await service.accept(
            candidate_id,
            by=principal.user_id,
            override=body.override,
            reason=body.reason,
            now=datetime.now(UTC),
        )
    except DecisionRefusedError as error:
        raise _refused(error) from error
    if found is None:
        raise _missing("candidate")
    detail = candidate_detail(found)
    await session.commit()
    await queue_model_build(principal.workspace_id)
    return detail


@router.post("/enrichment/candidates/{candidate_id}/reject", response_model=CandidateDetail)
async def reject(
    candidate_id: uuid.UUID,
    body: Decision,
    session: SessionDep,
    service: Curating,
    principal: Approver,
) -> CandidateDetail:
    """Not so: never proposed again under its key. An accepted candidate is
    withdrawn from the model — the next build, queued now, undoes it."""
    try:
        found = await service.reject(
            candidate_id, by=principal.user_id, reason=body.reason, now=datetime.now(UTC)
        )
    except DecisionRefusedError as error:
        raise _refused(error) from error
    if found is None:
        raise _missing("candidate")
    rejected, applied = found
    detail = candidate_detail(rejected)
    await session.commit()
    if applied:
        await queue_model_build(principal.workspace_id)
    return detail


@router.post(
    "/enrichment/candidates/{candidate_id}/reprocess",
    response_model=Reprocessed,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reprocess(
    candidate_id: uuid.UUID, session: SessionDep, service: Curating, principal: Approver
) -> Reprocessed:
    """Back to its analysis, which runs now: proposed again if its evidence
    still holds, withdrawn otherwise. 409 for one in the model: reject it
    first."""
    try:
        found = await service.reprocess(candidate_id, by=principal.user_id, now=datetime.now(UTC))
    except DecisionRefusedError as error:
        raise _refused(error) from error
    if found is None:
        raise _missing("candidate")
    read = candidate_read(found)
    await session.commit()
    queued = await queue_run(
        principal.workspace_id, trigger="request", by=principal.user_id, analyzers=[found.analyzer]
    )
    return Reprocessed(candidate=read, queued=queued)
