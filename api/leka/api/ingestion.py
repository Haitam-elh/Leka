"""Pipeline runs, and the sync of each source (LEKA-352).

    POST /ingestion/sources/{id}/sync     "sync now" — source:manage
    GET  /ingestion/sources/{id}/syncs    where each capability stands
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
from leka.ingestion import SourceSyncRead, SourceSyncRepository, SyncRequested, SyncSummary
from leka.ingestion.sync import SYNCABLE, enqueue_sync

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


@router.get("/sources/{source_id}/syncs", response_model=list[SourceSyncRead])
async def source_syncs(
    source_id: uuid.UUID, session: SessionDep, principal: Reader
) -> list[SourceSyncRead]:
    """Where each capability of the source stands, in capability order."""
    await _source(session, principal, source_id)
    rows = await SourceSyncRepository(session, principal.workspace_id).for_source(source_id)
    return [SourceSyncRead.model_validate(row, from_attributes=True) for row in rows]


@router.get("/syncs", response_model=list[SyncSummary])
async def sync_summaries(session: SessionDep, principal: Reader) -> list[SyncSummary]:
    """One line per source of the workspace that has been read at least once."""
    rows = await SourceSyncRepository(session, principal.workspace_id).summaries()
    return [
        SyncSummary(source_id=source_id, records_total=total, last_succeeded_at=last)
        for source_id, total, last in rows
    ]
