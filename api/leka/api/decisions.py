"""Decisions on intentions, over HTTP (LEKA-390).

    GET  /decisions?status=…            À valider: the decisions in a state, with their intention
    GET  /decisions/summary             how many stand where
    GET  /decisions/policy              how many must approve, per risk
    PUT  /decisions/policy              changed — by who may change the workspace
    GET  /intentions/{id}/decisions     every decision on it, the latest first
    POST /intentions/{id}/decision/{verdict}   approve, reject, modify, request-changes

Reading needs `intention:read`; voting `intention:approve` — and the
policy may want someone else than who asked. Every vote is kept with who,
when, why and the context it was cast in; the intention moved once decided.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission
from leka.intentions import (
    ApprovalPolicyRead,
    ApprovalPolicyUpdate,
    Change,
    DecisionClosedError,
    DecisionQueuePage,
    DecisionRead,
    DecisionRefusedError,
    DecisionService,
    DecisionSummary,
    DecisionVoteRequest,
    IllegalTransitionError,
    PolicyError,
    Verdict,
    policy_read,
)

router = APIRouter(tags=["decisions"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]
Admin = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))]

# The queue's states, as À valider names them.
QUEUES: dict[str, tuple[str, ...]] = {
    "proposed": ("proposed",),
    "approved": ("approved",),
    "rejected": ("rejected",),
    "withdrawn": ("changes_requested", "superseded"),
}
VERDICTS = {
    "approve": Verdict.APPROVE,
    "reject": Verdict.REJECT,
    "modify": Verdict.MODIFY,
    "request-changes": Verdict.REQUEST_CHANGES,
}
FORBIDDEN = {"asker_may_not_approve"}
CONFLICTING = {"already_approved"}


def _missing() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such intention.")


def _refused(error: DecisionRefusedError) -> ApiError:
    """Why a vote cannot be cast — its code in `details`, for the interface
    to say it."""
    code = (
        status.HTTP_403_FORBIDDEN
        if error.code in FORBIDDEN
        else status.HTTP_409_CONFLICT
        if error.code in CONFLICTING
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    kind = (
        ErrorCode.PERMISSION_DENIED
        if code == status.HTTP_403_FORBIDDEN
        else ErrorCode.CONFLICT
        if code == status.HTTP_409_CONFLICT
        else ErrorCode.VALIDATION_FAILED
    )
    return ApiError(
        code, kind, str(error), details=[FieldError(field="refusal", message=error.code)]
    )


@router.get("/decisions", response_model=DecisionQueuePage)
async def queue(
    principal: Reader,
    session: SessionDep,
    state: Annotated[
        Literal["proposed", "approved", "rejected", "withdrawn"], Query(alias="status")
    ] = "proposed",
) -> DecisionQueuePage:
    """The decisions in this state of À valider, the latest first, each with
    the intention it is on."""
    service = DecisionService(session, principal.workspace_id)
    return DecisionQueuePage(data=await service.queue(QUEUES[state]))


@router.get("/decisions/summary", response_model=DecisionSummary)
async def summary(principal: Reader, session: SessionDep) -> DecisionSummary:
    return await DecisionService(session, principal.workspace_id).summary()


@router.get("/decisions/policy", response_model=ApprovalPolicyRead)
async def policy(principal: Reader, session: SessionDep) -> ApprovalPolicyRead:
    """How many must approve, per risk, and when the asker may not be one —
    the workspace's, or LEKA's default."""
    _, said = await DecisionService(session, principal.workspace_id).policy()
    return policy_read(said)


@router.put("/decisions/policy", response_model=ApprovalPolicyRead)
async def set_policy(
    payload: ApprovalPolicyUpdate, principal: Admin, session: SessionDep
) -> ApprovalPolicyRead:
    """Changed for the decisions opened from now on: those open keep the
    policy they were opened with. 422 when it cannot be kept."""
    try:
        changed = await DecisionService(session, principal.workspace_id).set_policy(
            payload.model_dump(exclude_none=True)
        )
    except PolicyError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, str(error)
        ) from error
    await session.commit()
    return changed


@router.get("/intentions/{intention_id}/decisions", response_model=list[DecisionRead])
async def decisions(
    intention_id: uuid.UUID, principal: Reader, session: SessionDep
) -> list[DecisionRead]:
    """Every decision on it, the latest first, each with its votes."""
    found = await DecisionService(session, principal.workspace_id).decisions(intention_id)
    if found is None:
        raise _missing()
    return found


@router.post("/intentions/{intention_id}/decision/{verdict}", response_model=DecisionRead)
async def vote(
    intention_id: uuid.UUID,
    verdict: Literal["approve", "reject", "modify", "request-changes"],
    payload: DecisionVoteRequest,
    principal: Approver,
    session: SessionDep,
) -> DecisionRead:
    """A vote on the decision open on it, kept with who, when, why and its
    context. Rejecting, modifying and asking for changes say why. Modifying
    says where it should run, which actions are kept: a new revision, its
    risk read again, the earlier approvals void. 409 when nothing is open."""
    service = DecisionService(session, principal.workspace_id)
    try:
        decided = await service.vote(
            intention_id,
            VERDICTS[verdict],
            by=principal.user_id,
            reason=payload.reason,
            change=Change(
                environment=payload.environment,
                keep=tuple(payload.keep) if payload.keep is not None else None,
            ),
        )
    except DecisionRefusedError as error:
        raise _refused(error) from error
    except (DecisionClosedError, IllegalTransitionError) as error:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.CONFLICT,
            "Nothing to decide: no decision is open on this intention.",
        ) from error
    if decided is None:
        raise _missing()
    await session.commit()
    return decided
