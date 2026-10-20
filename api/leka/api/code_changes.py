"""Code changes an agent proposed, over HTTP.

    GET    /code-changes?intention_id&run_id   the workspace's, the latest first
    GET    /code-changes/{id}                  one: its files and their diffs
    POST   /code-changes/{id}/accept {note?}   its pull request, opened — 409
                                               when its source does not allow
                                               it, or GitHub refuses: it stays
                                               proposed, said why
    POST   /code-changes/{id}/reject {note?}   rejected, said why
    POST   /code-changes/{id}/follow           its pull request read again on
                                               GitHub, read only: its checks,
                                               its merge, its deployment

Reading takes `intention:read`; deciding, `intention:approve` — who may
approve what an intention asks to do. The workspace is the session's.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    ChangeDecidedError,
    ChangeNotFoundError,
    ChangeRefusedError,
    ChangeService,
    CodeChange,
    CodeChangeDecision,
    CodeChangeFileRead,
    CodeChangeFollow,
    CodeChangeRead,
    files_read,
)
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission
from leka.identity import User

router = APIRouter(prefix="/code-changes", tags=["capabilities"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]


def _missing() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such code change.")


async def _read(service: ChangeService, change: CodeChange) -> CodeChangeRead:
    return CodeChangeRead(
        id=change.id,
        run_id=change.run_id,
        intention_id=change.intention_id,
        repository=change.repository,
        base_branch=change.base_branch,
        title=change.title,
        summary=change.summary,
        status=change.status,
        files=[CodeChangeFileRead.model_validate(f) for f in files_read(change.files)],
        pull_requests_allowed=await service.allowed(change),
        source_id=change.source_id,
        proposed_by=change.proposed_by,
        decided_by=change.decided_by,
        decided_at=change.decided_at,
        note=change.note,
        branch=change.branch,
        pull_request_number=change.pull_request_number,
        pull_request_url=change.pull_request_url,
        error=change.error,
        error_detail=change.error_detail,
        follow=CodeChangeFollow.model_validate(change.follow) if change.follow else None,
        created_at=change.created_at,
    )


@router.get("", response_model=list[CodeChangeRead], summary="The code changes agents proposed")
async def list_changes(
    session: SessionDep,
    principal: Reader,
    intention_id: Annotated[uuid.UUID | None, Query()] = None,
    run_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[CodeChangeRead]:
    service = ChangeService(session, principal.workspace_id)
    found = await service.changes(intention_id=intention_id, run_id=run_id)
    return [await _read(service, change) for change in found]


@router.get("/{change_id}", response_model=CodeChangeRead, summary="One code change, its diffs")
async def get_change(
    change_id: uuid.UUID, session: SessionDep, principal: Reader
) -> CodeChangeRead:
    service = ChangeService(session, principal.workspace_id)
    try:
        return await _read(service, await service.change(change_id))
    except ChangeNotFoundError:
        raise _missing() from None


def _decided(error: ChangeDecidedError) -> ApiError:
    return ApiError(
        status.HTTP_409_CONFLICT,
        ErrorCode.CONFLICT,
        "This code change was already decided.",
        details=[FieldError(field="status", message=str(error))],
    )


@router.post(
    "/{change_id}/accept",
    response_model=CodeChangeRead,
    summary="Accept a code change: LEKA opens its pull request",
)
async def accept_change(
    change_id: uuid.UUID,
    session: SessionDep,
    principal: Approver,
    body: CodeChangeDecision | None = None,
) -> CodeChangeRead:
    service = ChangeService(session, principal.workspace_id)
    person = await session.get(User, principal.user_id)
    name = " ".join(
        part for part in ((person.first_name, person.last_name) if person else ()) if part
    )
    try:
        change = await service.accept(
            change_id,
            by=principal.user_id,
            by_name=name or "une personne de l'espace",
            note=body.note if body else None,
        )
    except ChangeNotFoundError:
        raise _missing() from None
    except ChangeDecidedError as error:
        raise _decided(error) from None
    except ChangeRefusedError as refused:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.CONFLICT,
            str(refused),
            details=[FieldError(field="pull_request", message=refused.code)],
        ) from None
    return await _read(service, change)


@router.post("/{change_id}/reject", response_model=CodeChangeRead, summary="Reject a code change")
async def reject_change(
    change_id: uuid.UUID,
    session: SessionDep,
    principal: Approver,
    body: CodeChangeDecision | None = None,
) -> CodeChangeRead:
    service = ChangeService(session, principal.workspace_id)
    try:
        change = await service.reject(
            change_id, by=principal.user_id, note=body.note if body else None
        )
    except ChangeNotFoundError:
        raise _missing() from None
    except ChangeDecidedError as error:
        raise _decided(error) from None
    return await _read(service, change)


@router.post(
    "/{change_id}/follow",
    response_model=CodeChangeRead,
    summary="Read its pull request again: checks, merge, deployment",
)
async def follow_change(
    change_id: uuid.UUID, session: SessionDep, principal: Reader
) -> CodeChangeRead:
    service = ChangeService(session, principal.workspace_id)
    try:
        # A click is enough: not GitHub again within ten seconds.
        return await _read(service, await service.follow(change_id, unless_within=10))
    except ChangeNotFoundError:
        raise _missing() from None
