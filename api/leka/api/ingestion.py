"""Pipeline runs, and the sync of each source (LEKA-352).

    POST /ingestion/sources/{id}/sync     "sync now" — source:manage
    GET  /ingestion/sources/{id}/syncs    a pass under way?, and each capability
    GET  /ingestion/syncs                 one line per source, for a list

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
from leka.background import JobQueue
from leka.connectors import Source, SourceNotFoundError, SourceService
from leka.core.errors import ErrorCode
from leka.governance import Permission, Principal, require_permission
from leka.ingestion import (
    SourceSyncRead,
    SourceSyncRepository,
    SourceSyncs,
    SyncRequested,
    SyncRunStatus,
    SyncSummary,
)
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
    queued = await enqueue_sync(principal.workspace_id, source.id, full=full, queue=JobQueue.HIGH)
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
    capabilities = []
    for row in await repository.for_source(source_id):
        read = SourceSyncRead.model_validate(row, from_attributes=True)
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
