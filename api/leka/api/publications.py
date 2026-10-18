"""What LEKA proposes to send out of a deliverable — tickets for Jira, pages
for Confluence — over HTTP (2026-10-18).

    POST   /agent-runs/{id}/publications {kind, source_id, target}
                                       drafted by a worker from the run's
                                       deliverable: 202, drafting
    GET    /publications?run_id&intention_id   the workspace's, the latest first
    GET    /publications/{id}             one: its tickets or pages
    POST   /publications/{id}/accept {items?, note?}
                                       the ones chosen, created through the
                                       source — 409 when the source does not
                                       allow it: it stays proposed, said why
    POST   /publications/{id}/reject {note?}   rejected, said why

Asking takes `intention:create`; reading, `intention:read`; deciding,
`intention:approve`. The workspace is the session's.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    CapabilityRunRepository,
    Publication,
    PublicationCreate,
    PublicationDecidedError,
    PublicationDecision,
    PublicationItemRead,
    PublicationNotFoundError,
    PublicationRead,
    PublicationRefusedError,
    PublicationService,
    items_read,
    queue_draft,
)
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission

router = APIRouter(tags=["capabilities"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Asker = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]


def _missing() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such publication.")


# What a person can change, then try again: the source, the run, Atlassian.
CONFLICTS = frozenset(
    {
        "issues_off",
        "pages_off",
        "no_source",
        "not_finished",
        "not_allowed",
        "not_found",
        "title_taken",
        "invalid",
        "unavailable",
    }
)


def _refused(refused: PublicationRefusedError, field: str) -> ApiError:
    conflict = refused.code in CONFLICTS
    return ApiError(
        status.HTTP_409_CONFLICT if conflict else status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.CONFLICT if conflict else ErrorCode.VALIDATION_FAILED,
        str(refused),
        details=[FieldError(field=field, message=refused.code)],
    )


async def _read(service: PublicationService, publication: Publication) -> PublicationRead:
    return PublicationRead(
        id=publication.id,
        run_id=publication.run_id,
        intention_id=publication.intention_id,
        kind=publication.kind,
        source_id=publication.source_id,
        target=publication.target,
        title=publication.title,
        summary=publication.summary,
        status=publication.status,
        items=[PublicationItemRead.model_validate(i) for i in items_read(publication)],
        allowed=await service.allowed(publication),
        proposed_by=publication.proposed_by,
        decided_by=publication.decided_by,
        decided_at=publication.decided_at,
        note=publication.note,
        error=publication.error,
        error_detail=publication.error_detail,
        created_at=publication.created_at,
    )


@router.post(
    "/agent-runs/{run_id}/publications",
    response_model=PublicationRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Tickets for Jira, or pages for Confluence, drafted from a run's deliverable",
)
async def ask_publication(
    run_id: uuid.UUID, body: PublicationCreate, session: SessionDep, principal: Asker
) -> PublicationRead:
    """Drafted by a worker — the model, from what the agent delivered.
    404 when the run is not there; 409 when it is not finished or the source
    is gone; 422 when the source is not of that kind, or the project or the
    space is not one it reads."""
    run = await CapabilityRunRepository(session, principal.workspace_id).run(run_id)
    if run is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such agent run.")
    service = PublicationService(session, principal.workspace_id)
    try:
        publication = await service.ask(
            run,
            kind=body.kind,
            source_id=body.source_id,
            target=body.target,
            by=principal.user_id,
        )
    except PublicationRefusedError as refused:
        field = (
            "source_id"
            if "source" in refused.code
            else "run_id"
            if refused.code == "not_finished"
            else "target"
        )
        raise _refused(refused, field) from None
    await session.commit()
    if not await queue_draft(principal.workspace_id, publication.id):
        publication.status, publication.error = "failed", "queue_down"
        await session.commit()
    return await _read(service, publication)


@router.get(
    "/publications",
    response_model=list[PublicationRead],
    summary="What LEKA proposed to send to Jira or Confluence",
)
async def list_publications(
    session: SessionDep,
    principal: Reader,
    run_id: Annotated[uuid.UUID | None, Query()] = None,
    intention_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[PublicationRead]:
    service = PublicationService(session, principal.workspace_id)
    found = await service.publications(run_id=run_id, intention_id=intention_id)
    return [await _read(service, publication) for publication in found]


@router.get(
    "/publications/{publication_id}", response_model=PublicationRead, summary="One publication"
)
async def get_publication(
    publication_id: uuid.UUID, session: SessionDep, principal: Reader
) -> PublicationRead:
    service = PublicationService(session, principal.workspace_id)
    try:
        return await _read(service, await service.publication(publication_id))
    except PublicationNotFoundError:
        raise _missing() from None


def _decided(error: PublicationDecidedError) -> ApiError:
    return ApiError(
        status.HTTP_409_CONFLICT,
        ErrorCode.CONFLICT,
        "This publication is not waiting for a decision.",
        details=[FieldError(field="status", message=str(error))],
    )


@router.post(
    "/publications/{publication_id}/accept",
    response_model=PublicationRead,
    summary="Accept a publication: LEKA creates the tickets or pages chosen",
)
async def accept_publication(
    publication_id: uuid.UUID,
    session: SessionDep,
    principal: Approver,
    body: PublicationDecision | None = None,
) -> PublicationRead:
    service = PublicationService(session, principal.workspace_id)
    try:
        publication = await service.accept(
            publication_id,
            by=principal.user_id,
            chosen=body.items if body else None,
            note=body.note if body else None,
        )
    except PublicationNotFoundError:
        raise _missing() from None
    except PublicationDecidedError as error:
        raise _decided(error) from None
    except PublicationRefusedError as refused:
        raise _refused(refused, "items" if refused.code == "nothing_chosen" else "source") from None
    return await _read(service, publication)


@router.post(
    "/publications/{publication_id}/reject",
    response_model=PublicationRead,
    summary="Reject a publication",
)
async def reject_publication(
    publication_id: uuid.UUID,
    session: SessionDep,
    principal: Approver,
    body: PublicationDecision | None = None,
) -> PublicationRead:
    service = PublicationService(session, principal.workspace_id)
    try:
        publication = await service.reject(
            publication_id, by=principal.user_id, note=body.note if body else None
        )
    except PublicationNotFoundError:
        raise _missing() from None
    except PublicationDecidedError as error:
        raise _decided(error) from None
    return await _read(service, publication)
