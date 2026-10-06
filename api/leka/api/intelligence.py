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

Read by every member (`workspace:read`), like the company model they are
drawn from. Asking for a run is asking LEKA something, like an intention:
`intention:create`, refused to a suspended workspace. A route validates,
calls one service, and returns (architecture rule 6); the workspace is the
session's (rule 3): another workspace's run or finding is 404.
"""

from __future__ import annotations

import uuid
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
    Finding,
    FindingDetail,
    FindingFilters,
    FindingRead,
    IntelligenceRepository,
    IntelligenceRun,
    IntelligenceService,
    IntelligenceSummary,
    RunDetail,
    RunRead,
    UnknownAnalyzerError,
)
from leka.intelligence.job import queue_run
from leka.knowledge import GraphRepository, GraphService

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Asker = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]

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
    subject: Annotated[uuid.UUID | None, Query(description="About this entity or context.")] = None,
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
