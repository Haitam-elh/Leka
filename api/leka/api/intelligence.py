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

    GET  /intelligence/conflicts         what the model's sources disagree on
                                         (LEKA-382), each side weighed, one
                                         recommended — by state, kind, thing
    GET  /intelligence/conflicts/{id}    one: every side, its sources, how
                                         much each is believed, the history
    GET  /intelligence/conflicts/summary how many are open, resolved…
    POST .../conflicts/{id}/resolve      keep a side: the model shows it from
                                         the next build on — and, asked, its
                                         source preferred on this from now on
    POST .../conflicts/{id}/dismiss      no contradiction
    POST .../conflicts/{id}/reopen       the decision withdrawn
    GET/POST /intelligence/authority-rules, DELETE …/{id}
                                         the workspace's word on its sources

    GET  /intelligence/quality           how far what LEKA knows can be
                                         trusted (LEKA-381): the workspace,
                                         by area, the weakest, the trend
    GET  /intelligence/quality/scores    each thing's or area's score — by
                                         scope, level, column, area, thing
    GET  /intelligence/quality/scores/{key}  one: its factors, where it was
                                         read, its history

    GET  /intelligence/activity          what happened and what LEKA did over
                                         a period (LEKA-383): counts against
                                         the period before, day by day, the
                                         latest, what concerned most, who
                                         decided most

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
    ActivityRead,
    ActivityRepository,
    ActivityService,
    AnalysisRequest,
    AnalysisRequested,
    AnalyzerRead,
    Arbitration,
    ArbitrationService,
    AuthorityRuleCreate,
    AuthorityRuleRead,
    CandidateDetail,
    CandidateFilters,
    CandidateRead,
    ChangeImpactDetail,
    ChangeImpactTimeline,
    ConflictDetail,
    ConflictFilters,
    ConflictRead,
    ConflictSummary,
    Decision,
    DecisionRefusedError,
    Dismissal,
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
    KnowledgeConflict,
    KnowledgeQualityDetail,
    KnowledgeQualityRead,
    KnowledgeQualitySummary,
    QualityFilters,
    QualityRepository,
    QualityScoreRow,
    QualityService,
    Reprocessed,
    RunDetail,
    RunRead,
    UnknownAnalyzerError,
    candidate_detail,
    candidate_read,
    candidate_reads,
    conflict_detail,
    conflict_reads,
    quality_reads,
)
from leka.intelligence.activity import MAX_LATEST
from leka.intelligence.job import queue_run
from leka.knowledge import (
    AssertionRepository,
    EntityRepository,
    EvolutionRepository,
    GraphRepository,
    GraphService,
    days_between,
    queue_model_build,
    zone,
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
CONFLICT_SORTS = SortCatalogue(
    fields=(
        SortableField(
            "last_seen_at", KnowledgeConflict.last_seen_at, "ix_knowledge_conflicts_workspace_seen"
        ),
    ),
    default="last_seen_at",
)
QUALITY_SORTS = SortCatalogue(
    fields=(
        SortableField("score", QualityScoreRow.score, "ix_quality_scores_workspace_scope_score"),
        SortableField("measured_at", QualityScoreRow.measured_at, "one row per thing: hundreds"),
    ),
    default="score",
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


# ── conflicts (LEKA-382) ───────────────────────────────────────────────


def _arbitration(session: SessionDep, principal: Reader) -> ArbitrationService:
    return ArbitrationService(
        IntelligenceRepository(session, principal.workspace_id),
        AssertionRepository(session, principal.workspace_id),
        EntityRepository(session, principal.workspace_id),
    )


Arbitrating = Annotated[ArbitrationService, Depends(_arbitration)]


@router.get("/conflicts", response_model=PageEnvelope[ConflictRead])
async def conflicts(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    state: Annotated[
        Literal["open", "resolved", "dismissed", "gone"] | None,
        Query(alias="status", description="Where it stands; none: all."),
    ] = None,
    kind: Annotated[Literal["attribute", "relationship"] | None, Query()] = None,
    subject: Annotated[uuid.UUID | None, Query(description="About this entity.")] = None,
) -> PageEnvelope[ConflictRead]:
    """What the model's sources disagree on, the latest seen first: every
    side weighed, one recommended."""
    statement = IntelligenceRepository(session, principal.workspace_id).conflicts(
        ConflictFilters(status=state, kind=kind, subject_id=subject)
    )
    result = await serve_page(
        session, statement, request=page, catalogue=CONFLICT_SORTS, id_column=KnowledgeConflict.id
    )
    return PageEnvelope(data=conflict_reads(result.items), next_cursor=result.next_cursor)


@router.get("/conflicts/summary", response_model=ConflictSummary)
async def conflict_summary(service: Arbitrating) -> ConflictSummary:
    """How many are open, resolved, dismissed, gone."""
    return await service.summary()


@router.get("/conflicts/{conflict_id}", response_model=ConflictDetail)
async def conflict(
    conflict_id: uuid.UUID, session: SessionDep, principal: Reader
) -> ConflictDetail:
    """One conflict: every side, who says it, how much each is believed and
    why, what LEKA recommends, every decision taken."""
    found = await IntelligenceRepository(session, principal.workspace_id).conflict(conflict_id)
    if found is None:
        raise _missing("conflict")
    return conflict_detail(found)


@router.post("/conflicts/{conflict_id}/resolve", response_model=ConflictDetail)
async def resolve(
    conflict_id: uuid.UUID,
    body: Arbitration,
    session: SessionDep,
    service: Arbitrating,
    principal: Approver,
) -> ConflictDetail:
    """Keep a side: the model shows it from its next build on — queued now —
    whoever says otherwise; for a relationship a thing has one of, the
    others are refuted. `remember`: prefer this side's source on this from
    now on. 409 for a conflict no longer disagreed on, a side it does not
    have, or a thing gone."""
    try:
        found = await service.resolve(
            conflict_id,
            side=body.side,
            by=principal.user_id,
            reason=body.reason,
            remember=body.remember,
            now=datetime.now(UTC),
        )
    except DecisionRefusedError as error:
        raise _refused(error) from error
    if found is None:
        raise _missing("conflict")
    detail = conflict_detail(found)
    await session.commit()
    await queue_model_build(principal.workspace_id)
    return detail


@router.post("/conflicts/{conflict_id}/dismiss", response_model=ConflictDetail)
async def dismiss(
    conflict_id: uuid.UUID,
    body: Dismissal,
    session: SessionDep,
    service: Arbitrating,
    principal: Approver,
) -> ConflictDetail:
    """No contradiction: the model goes on as resolution chose — an earlier
    decision withdrawn."""
    try:
        found = await service.dismiss(
            conflict_id, by=principal.user_id, reason=body.reason, now=datetime.now(UTC)
        )
    except DecisionRefusedError as error:
        raise _refused(error) from error
    if found is None:
        raise _missing("conflict")
    detail = conflict_detail(found)
    await session.commit()
    await queue_model_build(principal.workspace_id)
    return detail


@router.post("/conflicts/{conflict_id}/reopen", response_model=ConflictDetail)
async def reopen(
    conflict_id: uuid.UUID, session: SessionDep, service: Arbitrating, principal: Approver
) -> ConflictDetail:
    """The decision withdrawn: open again, the model as before it at its
    next build. 409 for one not decided."""
    try:
        found = await service.reopen(conflict_id, by=principal.user_id, now=datetime.now(UTC))
    except DecisionRefusedError as error:
        raise _refused(error) from error
    if found is None:
        raise _missing("conflict")
    reopened, withdrawn = found
    detail = conflict_detail(reopened)
    await session.commit()
    if withdrawn:
        await queue_model_build(principal.workspace_id)
    return detail


@router.get("/authority-rules", response_model=list[AuthorityRuleRead])
async def authority_rules(service: Arbitrating) -> list[AuthorityRuleRead]:
    """The workspace's word on its sources: on what each is preferred or
    avoided."""
    return await service.rules()


@router.post(
    "/authority-rules", response_model=AuthorityRuleRead, status_code=status.HTTP_201_CREATED
)
async def add_authority_rule(
    body: AuthorityRuleCreate, session: SessionDep, service: Arbitrating, principal: Approver
) -> AuthorityRuleRead:
    """Prefer or avoid a source on an attribute — or everything, `*`. Said
    again for the same source and attribute, replaced. LEKA's next
    recommendations follow it."""
    try:
        rule = await service.set_rule(
            about=body.about,
            source_id=body.source_id,
            stance=body.stance,
            reason=body.reason,
            by=principal.user_id,
        )
    except DecisionRefusedError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, error.detail) from error
    read = await service.rule_read(rule)
    await session.commit()
    return read


@router.delete("/authority-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_authority_rule(
    rule_id: uuid.UUID, session: SessionDep, service: Arbitrating, principal: Approver
) -> None:
    """Forget a rule: the source believed by its family again."""
    if not await service.delete_rule(rule_id):
        raise _missing("authority rule")
    await session.commit()


# ── knowledge quality (LEKA-381) ───────────────────────────────────────


def _quality(session: SessionDep, principal: Reader) -> QualityService:
    return QualityService(QualityRepository(session, principal.workspace_id))


Measuring = Annotated[QualityService, Depends(_quality)]


@router.get("/quality", response_model=KnowledgeQualitySummary)
async def quality(service: Measuring) -> KnowledgeQualitySummary:
    """How far what LEKA knows can be trusted: the workspace's score, each
    column's, team's and application's, the things known least well, and
    how the workspace's moved over 30 days."""
    return await service.summary(now=datetime.now(UTC))


@router.get("/quality/scores", response_model=PageEnvelope[KnowledgeQualityRead])
async def quality_scores(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    scope: Annotated[
        Literal["entity", "team", "application", "column", "workspace"] | None, Query()
    ] = None,
    level: Annotated[Literal["high", "medium", "low"] | None, Query()] = None,
    column: Annotated[str | None, Query(max_length=20)] = None,
    area: Annotated[
        str | None,
        Query(max_length=300, description="Counted in this area: team:<id>, application:<id>…"),
    ] = None,
    subject: Annotated[uuid.UUID | None, Query(description="About this entity.")] = None,
) -> PageEnvelope[KnowledgeQualityRead]:
    """The scores by score (`sort=score`, the default) — `order=asc` for
    the weakest first — or the latest measured (`sort=measured_at`)."""
    statement = QualityRepository(session, principal.workspace_id).scores(
        QualityFilters(scope=scope, level=level, column=column, area=area, subject_id=subject)
    )
    result = await serve_page(
        session, statement, request=page, catalogue=QUALITY_SORTS, id_column=QualityScoreRow.id
    )
    return PageEnvelope(data=quality_reads(result.items), next_cursor=result.next_cursor)


@router.get("/quality/scores/{key}", response_model=KnowledgeQualityDetail)
async def quality_score(key: str, service: Measuring) -> KnowledgeQualityDetail:
    """One score: each dimension's factors, what lowers it and what shows
    it, where it was read, its changes over 90 days."""
    found = await service.detail(key, now=datetime.now(UTC))
    if found is None:
        raise _missing("quality score")
    return found


# ── the activity (LEKA-383) ─────────────────────────────────────────────────

MAX_ACTIVITY_DAYS = 90


@router.get("/activity", response_model=ActivityRead)
async def activity(
    session: SessionDep,
    principal: Reader,
    days: Annotated[
        int, Query(ge=1, le=MAX_ACTIVITY_DAYS, description="The period: so many days.")
    ] = 7,
    timezone: Annotated[
        str | None, Query(max_length=64, description="The days' zone, IANA: Europe/Paris. UTC.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LATEST, description="The latest, at most.")] = 20,
) -> ActivityRead:
    """What happened in the environment and what LEKA did over the last
    `days` — the model built, the systems' events, the analyses, what they
    raised and proposed, the decisions — counted against the period before,
    day by day in the reader's zone; the latest; the services and
    applications most concerned; who decided most."""
    until = datetime.now(UTC)
    since = until - timedelta(days=days)
    tz = zone(timezone)
    return await ActivityService(
        ActivityRepository(session, principal.workspace_id),
        EvolutionRepository(session, principal.workspace_id),
    ).read(
        since=since,
        until=until,
        tz=tz,
        days=days_between(since, until, tz),
        limit=limit,
    )
