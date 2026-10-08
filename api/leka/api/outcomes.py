"""What came of intentions, and their whole story, over HTTP (LEKA-392).

    PUT  /intentions/{id}/plan/expectations          what should be true once it ran
    GET  /intentions/{id}/verifications              whether it came, the latest first
    POST /intentions/{id}/verification/check         read again now
    POST /intentions/{id}/verification/expectations/{expectation_id}/report
    POST /intentions/{id}/verification/conclude      concluded by a person
    GET  /intentions/{id}/timeline                   its story, filtered
    GET  /intention-history                          every intention's, filtered

Reading needs `intention:read`; setting expectations, reporting, checking
and concluding `intention:approve`. A success asks the model to be built
again: queued once the route has committed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission
from leka.intentions import (
    ExpectationRead,
    ExpectationReport,
    ExpectationsUpdate,
    Filters,
    IllegalTransitionError,
    IntentionArchivedError,
    IntentionRepository,
    IntentionVerificationRead,
    TimelineItem,
    VerificationConclude,
    VerificationRefusedError,
    VerificationService,
    categories_of,
    timeline,
)
from leka.knowledge import queue_model_build

router = APIRouter(tags=["outcomes"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]
Category = Literal["intention", "analysis", "decision", "action", "outcome"]


def _missing(what: str = "intention") -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"No such {what}.")


def _refused(error: Exception) -> ApiError:
    if isinstance(error, VerificationRefusedError):
        code = (
            status.HTTP_422_UNPROCESSABLE_CONTENT
            if error.code == "invalid_expectation"
            else status.HTTP_409_CONFLICT
        )
        return ApiError(
            code,
            ErrorCode.VALIDATION_FAILED if code == 422 else ErrorCode.CONFLICT,
            str(error),
            details=[FieldError(field="refusal", message=error.code)],
        )
    return ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, str(error))


REFUSED = (VerificationRefusedError, IllegalTransitionError, IntentionArchivedError)


async def _built(service: VerificationService, principal: Principal) -> None:
    if service.build:
        await queue_model_build(principal.workspace_id)


@router.put("/intentions/{intention_id}/plan/expectations", response_model=list[ExpectationRead])
async def set_expectations(
    intention_id: uuid.UUID, payload: ExpectationsUpdate, principal: Approver, session: SessionDep
) -> list[ExpectationRead]:
    """What should be true once it ran — set before it runs. 409 once it
    started; 422 for one that cannot be checked as said."""
    try:
        kept = await VerificationService(session, principal.workspace_id).set_expectations(
            intention_id,
            [e.model_dump(mode="json") for e in payload.expectations],
            by=principal.user_id,
        )
    except REFUSED as error:
        raise _refused(error) from error
    if kept is None:
        raise _missing()
    await session.commit()
    return [ExpectationRead.model_validate(e) for e in kept]


@router.get(
    "/intentions/{intention_id}/verifications", response_model=list[IntentionVerificationRead]
)
async def verifications(
    intention_id: uuid.UUID, principal: Reader, session: SessionDep
) -> list[IntentionVerificationRead]:
    found = await VerificationService(session, principal.workspace_id).verifications(intention_id)
    if found is None:
        raise _missing()
    return found


@router.post(
    "/intentions/{intention_id}/verification/check", response_model=IntentionVerificationRead
)
async def check(
    intention_id: uuid.UUID, principal: Approver, session: SessionDep
) -> IntentionVerificationRead:
    """Read again now, without waiting for the sweep."""
    service = VerificationService(session, principal.workspace_id)
    try:
        read = await service.check_now(intention_id)
    except REFUSED as error:
        raise _refused(error) from error
    if read is None:
        raise _missing()
    await session.commit()
    await _built(service, principal)
    return read


@router.post(
    "/intentions/{intention_id}/verification/expectations/{expectation_id}/report",
    response_model=IntentionVerificationRead,
)
async def report(
    intention_id: uuid.UUID,
    expectation_id: str,
    payload: ExpectationReport,
    principal: Approver,
    session: SessionDep,
) -> IntentionVerificationRead:
    """A person's word on one expectation, with what shows it."""
    service = VerificationService(session, principal.workspace_id)
    try:
        read = await service.report(
            intention_id,
            expectation_id,
            met=payload.met,
            note=payload.note,
            link=str(payload.link) if payload.link else None,
            by=principal.user_id,
        )
    except REFUSED as error:
        raise _refused(error) from error
    if read is None:
        raise _missing("expectation")
    await session.commit()
    await _built(service, principal)
    return read


@router.post(
    "/intentions/{intention_id}/verification/conclude", response_model=IntentionVerificationRead
)
async def conclude(
    intention_id: uuid.UUID, payload: VerificationConclude, principal: Approver, session: SessionDep
) -> IntentionVerificationRead:
    """Concluded now, with what is observed: what is not met counts so."""
    service = VerificationService(session, principal.workspace_id)
    try:
        read = await service.conclude(intention_id, by=principal.user_id, note=payload.note)
    except REFUSED as error:
        raise _refused(error) from error
    if read is None:
        raise _missing()
    await session.commit()
    await _built(service, principal)
    return read


TimelineFilters = Annotated[list[Category] | None, Query(alias="category")]


@router.get("/intentions/{intention_id}/timeline", response_model=list[TimelineItem])
async def intention_timeline(
    intention_id: uuid.UUID,
    principal: Reader,
    session: SessionDep,
    category: TimelineFilters = None,
    actor: Literal["person", "system"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[TimelineItem]:
    """Its whole story — what happened to it, its analyses, its decision
    and votes, its plan and steps, its outcome — the latest first."""
    if await IntentionRepository(session, principal.workspace_id).intention(intention_id) is None:
        raise _missing()
    return await timeline(
        session,
        principal.workspace_id,
        Filters(
            intention_id=intention_id,
            categories=categories_of(category),
            actor=actor,
            since=since,
            until=until,
            limit=limit,
        ),
    )


@router.get("/intention-history", response_model=list[TimelineItem])
async def history(
    principal: Reader,
    session: SessionDep,
    category: TimelineFilters = None,
    actor: Literal["person", "system"] | None = None,
    by: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[TimelineItem]:
    """Every intention's story, the latest first: what happened, of which
    kind, by whom — filtered."""
    return await timeline(
        session,
        principal.workspace_id,
        Filters(
            categories=categories_of(category),
            actor=actor,
            by=by,
            since=since,
            until=until,
            limit=limit,
        ),
    )
