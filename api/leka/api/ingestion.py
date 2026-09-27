"""Pipeline runs, and the sync of each source (LEKA-352).

    POST /ingestion/sources/{id}/sync     "sync now" — source:manage
    GET  /ingestion/sources/{id}/syncs    a pass under way?, and each capability
    GET  /ingestion/sources/{id}/runs     its passes, newest first (LEKA-353)
    GET  /ingestion/syncs                 one line per source, for a list
    GET  /ingestion/sources/{id}/extraction  what extraction made of it (LEKA-354)
    GET  /ingestion/sources/{id}/parsing     what parsing read in it (LEKA-355)
    GET  /ingestion/sources/{id}/normalisation  the candidates made of it (LEKA-356)
    GET  /ingestion/sources/{id}/pipeline       each stage: under way, pending, last run (LEKA-360)
    GET  /ingestion/sources/{id}/processing-runs  every run, newest first
    POST /ingestion/sources/{id}/pipeline/resume     queue what has work — source:manage
    POST /ingestion/sources/{id}/pipeline/reprocess  drop a stage's rows, redo — source:manage

A route validates, calls one service, and returns (architecture rule 6).
Permissions come from a FastAPI dependency, never an `if` in the body
(rule 5). The workspace is read from the session, never from the path or the
payload (rule 3): another workspace's source is a 404, as on /sources.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.background import JobQueue
from leka.connectors import Source, SourceNotFoundError, SourceService
from leka.core.errors import ErrorCode
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission
from leka.ingestion import (
    ExtractionFailureRead,
    ExtractionRepository,
    ExtractorCount,
    NormalisationFailureRead,
    NormalisationRepository,
    ParseFailureRead,
    ParsingRepository,
    PipelineQueued,
    ProcessingRun,
    ProcessingRunRead,
    ProcessingRunRepository,
    ProcessingStage,
    SourceExtraction,
    SourceNormalisation,
    SourceParsing,
    SourcePipeline,
    SourceRecordRepository,
    SourceSyncRead,
    SourceSyncRepository,
    SourceSyncs,
    StageState,
    SyncRequested,
    SyncRun,
    SyncRunRead,
    SyncRunRepository,
    SyncRunStatus,
    SyncSummary,
    SyncTrigger,
)
from leka.ingestion.lifecycle import reprocess
from leka.ingestion.pipeline import STAGES, advance, pending
from leka.ingestion.sync import ABANDONED, SYNCABLE, enqueue_sync

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

Reader = Annotated[Principal, Depends(require_permission(Permission.SOURCE_READ))]
Manager = Annotated[Principal, Depends(require_permission(Permission.SOURCE_MANAGE))]


async def _source(session: SessionDep, principal: Principal, source_id: uuid.UUID) -> Source:
    service = SourceService(session, principal.workspace_id, actor_user_id=principal.user_id)
    try:
        return await service.get(source_id)
    except SourceNotFoundError as error:
        raise ApiError(404, ErrorCode.NOT_FOUND, "No such source in this workspace.") from error


@router.post(
    "/sources/{source_id}/sync",
    response_model=SyncRequested,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_now(
    source_id: uuid.UUID, session: SessionDep, principal: Manager, full: bool = False
) -> SyncRequested:
    """Read the source now rather than at the next scheduled pass.

    `full` ignores where the last pass stopped and reads everything. 202
    either way: `queued` is false when a pass is already on its way.
    """
    source = await _source(session, principal, source_id)
    if source.status not in SYNCABLE:
        raise ApiError(409, ErrorCode.CONFLICT, "Only an activated source can be synchronised.")
    # High: a person is waiting for it.
    queued = await enqueue_sync(
        principal.workspace_id,
        source.id,
        full=full,
        queue=JobQueue.HIGH,
        trigger=SyncTrigger.MANUAL,
    )
    return SyncRequested(queued=queued)


@router.get("/sources/{source_id}/syncs", response_model=SourceSyncs)
async def source_syncs(source_id: uuid.UUID, session: SessionDep, principal: Reader) -> SourceSyncs:
    """Whether a pass is under way, and where each capability stands.

    "running" only while a worker is really reading: a capability left
    `running` by a pass whose worker died is shown as the failure the next
    pass will record (leka/ingestion/sync.py, ABANDONED).
    """
    await _source(session, principal, source_id)
    repository = SourceSyncRepository(session, principal.workspace_id)
    under_way = (await repository.passes([source_id])).get(source_id)
    live = await SourceRecordRepository(session, principal.workspace_id).live_counts()
    capabilities = []
    for row in await repository.for_source(source_id):
        read = SourceSyncRead.model_validate(row, from_attributes=True)
        # What LEKA holds now, from the index; before a capability is indexed,
        # what was written (LEKA-352).
        read.records_total = live.get((source_id, row.capability), read.records_total)
        if read.status == SyncRunStatus.RUNNING.value and under_way != "running":
            read.status = SyncRunStatus.FAILED.value
            read.last_error = ABANDONED.model_dump(mode="json")
        capabilities.append(read)
    return SourceSyncs(pass_state=under_way, capabilities=capabilities)


@router.get("/syncs", response_model=list[SyncSummary])
async def sync_summaries(session: SessionDep, principal: Reader) -> list[SyncSummary]:
    """One line per source that has been read or has a pass under way."""
    repository = SourceSyncRepository(session, principal.workspace_id)
    read = {source_id: (total, last) for source_id, total, last in await repository.summaries()}
    live: dict[uuid.UUID, int] = {}
    for (source_id, _kind), count in (
        await SourceRecordRepository(session, principal.workspace_id).live_counts()
    ).items():
        live[source_id] = live.get(source_id, 0) + count
    # What LEKA holds now, from the index; before a source is indexed, what
    # was written (LEKA-352).
    read = {
        source_id: (live.get(source_id, total), last) for source_id, (total, last) in read.items()
    }
    ids = [source.id for source in await _sources(session, principal)]
    under_way = await repository.passes(ids)
    return [
        SyncSummary(
            source_id=source_id,
            records_total=read.get(source_id, (0, None))[0],
            last_succeeded_at=read.get(source_id, (0, None))[1],
            pass_state=under_way.get(source_id),
        )
        for source_id in ids
        if source_id in read or source_id in under_way
    ]


async def _sources(session: SessionDep, principal: Principal) -> list[Source]:
    service = SourceService(session, principal.workspace_id, actor_user_id=principal.user_id)
    return list(await service.repository.list(service.repository.list_statement()))


RUN_SORTS = SortCatalogue(
    fields=(SortableField("started_at", SyncRun.started_at, "ix_sync_runs_source_started_at"),),
    default="started_at",
)


@router.get("/sources/{source_id}/runs", response_model=PageEnvelope[SyncRunRead])
async def source_runs(
    source_id: uuid.UUID, session: SessionDep, principal: Reader, page: PageParams
) -> PageEnvelope[SyncRunRead]:
    """The source's passes, newest first — one still running shows how far it has got."""
    await _source(session, principal, source_id)
    result = await serve_page(
        session,
        SyncRunRepository(session, principal.workspace_id).history(source_id),
        request=page,
        catalogue=RUN_SORTS,
        id_column=SyncRun.id,
    )
    return PageEnvelope(
        data=[SyncRunRead.model_validate(run, from_attributes=True) for run in result.items],
        next_cursor=result.next_cursor,
    )


FAILURES_SHOWN = 20


@router.get("/sources/{source_id}/extraction", response_model=SourceExtraction)
async def source_extraction(
    source_id: uuid.UUID, session: SessionDep, principal: Reader
) -> SourceExtraction:
    """What extraction made of the source's records: how many, by which
    strategy, and the latest it could not — a vendor changing a payload's
    shape shows here as one strategy failing all at once."""
    await _source(session, principal, source_id)
    repository = ExtractionRepository(session, principal.workspace_id)
    counts = await repository.counts(source_id)
    per_extractor: dict[str | None, ExtractorCount] = {}
    for status_, _code, extractor, n in counts:
        line = per_extractor.setdefault(
            extractor, ExtractorCount(extractor=extractor, extracted=0, failed=0)
        )
        if status_ == "extracted":
            line.extracted += n
        else:
            line.failed += n
    return SourceExtraction(
        extracted=sum(n for s, _, _, n in counts if s == "extracted"),
        failed=sum(n for s, _, _, n in counts if s == "failed"),
        unsupported=sum(n for _, code, _, n in counts if code == "unsupported"),
        malformed=sum(n for _, code, _, n in counts if code == "malformed"),
        last_extracted_at=await repository.latest(source_id),
        extractors=sorted(per_extractor.values(), key=lambda c: c.extractor or ""),
        failures=[
            ExtractionFailureRead(
                capability=row.kind,
                external_id=external_id,
                extractor=row.extractor,
                code=str(row.failure_code),
                message=str(row.message),
                extracted_at=row.extracted_at,
            )
            for row, external_id in await repository.failures(source_id, limit=FAILURES_SHOWN)
        ],
    )


@router.get("/sources/{source_id}/parsing", response_model=SourceParsing)
async def source_parsing(
    source_id: uuid.UUID, session: SessionDep, principal: Reader
) -> SourceParsing:
    """What parsing read in the source's records: how many, the facts they
    gave by type, their average quality, and the latest it could not."""
    await _source(session, principal, source_id)
    repository = ParsingRepository(session, principal.workspace_id)
    counts = await repository.counts(source_id)
    return SourceParsing(
        parsed=counts.get("parsed", 0),
        failed=counts.get("failed", 0),
        facts=await repository.facts(source_id),
        average_quality=await repository.quality(source_id),
        last_parsed_at=await repository.latest(source_id),
        failures=[
            ParseFailureRead(
                capability=row.kind,
                external_id=external_id,
                code=str(row.failure_code),
                message=str(row.message),
                parsed_at=row.parsed_at,
            )
            for row, external_id in await repository.failures(source_id, limit=FAILURES_SHOWN)
        ],
    )


@router.get("/sources/{source_id}/normalisation", response_model=SourceNormalisation)
async def source_normalisation(
    source_id: uuid.UUID, session: SessionDep, principal: Reader
) -> SourceNormalisation:
    """The candidates normalisation made of the source's records: how many,
    their entities and relationships by type, how many kept something as
    the vendor wrote it, and the latest it could not make."""
    await _source(session, principal, source_id)
    repository = NormalisationRepository(session, principal.workspace_id)
    counts = await repository.counts(source_id)
    return SourceNormalisation(
        normalised=sum(n for s, _, n in counts if s == "normalised"),
        failed=sum(n for s, _, n in counts if s == "failed"),
        unsupported=sum(n for _, code, n in counts if code == "unsupported"),
        invalid=sum(n for _, code, n in counts if code == "invalid"),
        malformed=sum(n for _, code, n in counts if code == "malformed"),
        entities=await repository.entity_types(source_id),
        relationships=await repository.relationship_types(source_id),
        with_diagnostics=await repository.with_diagnostics(source_id),
        last_normalised_at=await repository.latest(source_id),
        failures=[
            NormalisationFailureRead(
                capability=row.kind,
                external_id=external_id,
                code=str(row.failure_code),
                message=str(row.message),
                normalised_at=row.normalised_at,
            )
            for row, external_id in await repository.failures(source_id, limit=FAILURES_SHOWN)
        ],
    )


@router.get("/sources/{source_id}/pipeline", response_model=SourcePipeline)
async def source_pipeline(
    source_id: uuid.UUID, session: SessionDep, principal: Reader
) -> SourcePipeline:
    """Each processing stage of the source, in order: whether a job has it,
    whether it has work, and how its last run went."""
    source = await _source(session, principal, source_id)
    runs = ProcessingRunRepository(session, principal.workspace_id)
    jobs = await runs.job_states({stage.key(source.id): stage.name for stage in STAGES})
    last = await runs.latest(source.id)
    stages = [
        StageState(
            stage=stage.name.value,
            job=jobs.get(stage.name),
            pending=await pending(session, principal.workspace_id, source, stage.name),
            last_run=ProcessingRunRead.model_validate(last[stage.name])
            if stage.name in last
            else None,
        )
        for stage in STAGES
    ]
    return SourcePipeline(
        stages=stages,
        processed_through=not any(s.pending or s.job for s in stages),
    )


PROCESSING_RUN_SORTS = SortCatalogue(
    fields=(
        SortableField(
            "started_at", ProcessingRun.started_at, "ix_processing_runs_source_stage_started"
        ),
    ),
    default="started_at",
)


@router.get("/sources/{source_id}/processing-runs", response_model=PageEnvelope[ProcessingRunRead])
async def source_processing_runs(
    source_id: uuid.UUID, session: SessionDep, principal: Reader, page: PageParams
) -> PageEnvelope[ProcessingRunRead]:
    """Every run of every stage over the source, newest first."""
    await _source(session, principal, source_id)
    result = await serve_page(
        session,
        ProcessingRunRepository(session, principal.workspace_id).history(source_id),
        request=page,
        catalogue=PROCESSING_RUN_SORTS,
        id_column=ProcessingRun.id,
    )
    return PageEnvelope(
        data=[ProcessingRunRead.model_validate(run) for run in result.items],
        next_cursor=result.next_cursor,
    )


@router.post(
    "/sources/{source_id}/pipeline/resume",
    response_model=PipelineQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_pipeline(
    source_id: uuid.UUID, session: SessionDep, principal: Manager
) -> PipelineQueued:
    """Queue the first stage that has work — after a failure that used up its
    retries, or to catch up now rather than after the next pass."""
    source = await _source(session, principal, source_id)
    queued = await advance(session, principal.workspace_id, source, after=None)
    return PipelineQueued(queued=queued.value if queued else None)


@router.post(
    "/sources/{source_id}/pipeline/reprocess",
    response_model=PipelineQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reprocess_pipeline(
    source_id: uuid.UUID, session: SessionDep, principal: Manager, stage: ProcessingStage
) -> PipelineQueued:
    """Drop what `stage` made for the source — and what the later stages made
    from it — then queue it again. Until it has run, the source has none of
    that stage's rows: a deliberate act, for a manager."""
    source = await _source(session, principal, source_id)
    queued = await reprocess(session, principal.workspace_id, source, stage)
    return PipelineQueued(queued=queued.value if queued else None)
