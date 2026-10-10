"""Decisions on intentions, over HTTP (LEKA-390), and their governance
(LEKA-404).

    GET  /decisions?status=…            À valider: the decisions in a state, with their intention
    GET  /decisions/summary             how many stand where
    GET  /decisions/policy              the governance policy: risk rules, and per risk the
                                        approvals, the asker apart, a role, how long an approval
                                        holds, when one waiting is escalated
    PUT  /decisions/policy              changed — by who may change the workspace; kept in the trail
    POST /decisions/policy/evaluate     what the policy says of an action, were it proposed now
    GET  /decisions/exceptions          freezes and waivers, past and present
    POST /decisions/exceptions          granted — by who may change the workspace
    POST /decisions/exceptions/{id}/revoke
    GET  /decisions/delegations         who lent their authority to approve, to whom
    POST /decisions/delegations         yours lent — by who may approve
    POST /decisions/delegations/{id}/revoke   by who lent it, or an admin
    GET  /decisions/governance-history  the trail: every change of governance, append-only
    GET  /intentions/{id}/decisions     every decision on it, the latest first
    POST /intentions/{id}/decision/{verdict}   approve, reject, modify, request-changes

Reading needs `intention:read`; voting `intention:approve` — or a
delegation from someone who holds it — and the policy may want someone
else than who asked, or a role. Every vote is kept with who, for whom, as
which role, when, why and the context it was cast in; the intention moved
once decided.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
    DelegationCreate,
    DelegationRead,
    ExceptionAsk,
    GovernanceEventRead,
    GovernanceExceptionCreate,
    GovernanceExceptionRead,
    IllegalTransitionError,
    OversightRefusedError,
    OversightService,
    PolicyError,
    PolicyProbe,
    PolicyVerdictRead,
    Verdict,
    policy_read,
)

router = APIRouter(tags=["decisions"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]
Admin = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))]
# Any member who may write: whether they may vote — theirs, or a delegated
# authority — is then checked.
Voter = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]

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
FORBIDDEN = {"asker_may_not_approve", "no_delegation"}
CONFLICTING = {"already_approved", "frozen"}


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
    """The governance policy — the workspace's, or LEKA's default: the
    rules that raise a risk, and per risk how many must approve, whether
    the asker may be one, a role one of them must hold, how long an
    approval holds, after how long one waiting is escalated."""
    _, said = await DecisionService(session, principal.workspace_id).policy()
    return policy_read(said)


@router.put("/decisions/policy", response_model=ApprovalPolicyRead)
async def set_policy(
    payload: ApprovalPolicyUpdate, principal: Admin, session: SessionDep
) -> ApprovalPolicyRead:
    """Changed for the decisions opened from now on: those open keep the
    policy they were opened with; one approved but not yet run must meet it.
    Per risk, what is not said is kept; a null role or hours, none. Kept in
    the governance trail. 422 when it cannot be kept."""
    try:
        changed = await DecisionService(session, principal.workspace_id).set_policy(
            payload.model_dump(exclude_unset=True), by=principal.user_id
        )
    except PolicyError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, str(error)
        ) from error
    await session.commit()
    return changed


@router.post("/decisions/policy/evaluate", response_model=PolicyVerdictRead)
async def evaluate_policy(
    payload: PolicyProbe, principal: Reader, session: SessionDep
) -> PolicyVerdictRead:
    """What the policy says of an action, were it proposed now: its risk
    and why, what it would need, whether a freeze or a waiver covers it.
    Nothing is kept."""
    return await DecisionService(session, principal.workspace_id).probe(
        payload.action,
        environment=payload.environment,
        targets=payload.targets,
        analysis_risk=payload.risk,
    )


def _oversight_refused(error: OversightRefusedError) -> ApiError:
    forbidden = error.code == "not_yours"
    conflict = error.code == "already_revoked"
    return ApiError(
        status.HTTP_403_FORBIDDEN
        if forbidden
        else status.HTTP_409_CONFLICT
        if conflict
        else status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.PERMISSION_DENIED
        if forbidden
        else ErrorCode.CONFLICT
        if conflict
        else ErrorCode.VALIDATION_FAILED,
        error.message,
        details=[FieldError(field="refusal", message=error.code)],
    )


def _gone(what: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"No such {what}.")


@router.get("/decisions/exceptions", response_model=list[GovernanceExceptionRead])
async def exceptions(principal: Reader, session: SessionDep) -> list[GovernanceExceptionRead]:
    """Every freeze and waiver, the latest first, each said active or not."""
    now = datetime.now(UTC)
    rows = await OversightService(session, principal.workspace_id).exception_rows()
    return [
        GovernanceExceptionRead.model_validate(r).model_copy(
            update={"active": r.revoked_at is None and r.starts_at <= now < r.ends_at}
        )
        for r in rows
    ]


@router.post(
    "/decisions/exceptions",
    response_model=GovernanceExceptionRead,
    status_code=status.HTTP_201_CREATED,
)
async def grant_exception(
    payload: GovernanceExceptionCreate, principal: Admin, session: SessionDep
) -> GovernanceExceptionRead:
    """A freeze — nothing it covers is approved nor run while it holds — or
    a waiver — what it covers, named actions in named environments, up to a
    medium risk, is approved in advance in your name. 422 when it cannot be
    granted as said."""
    now = datetime.now(UTC)
    try:
        row = await OversightService(session, principal.workspace_id).grant(
            ExceptionAsk(
                kind=payload.kind,
                reason=payload.reason,
                starts_at=payload.starts_at or now,
                ends_at=payload.ends_at,
                actions=tuple(payload.actions),
                environments=tuple(payload.environments),
                targets=tuple(payload.targets),
                max_risk=payload.max_risk,
            ),
            by=principal.user_id,
            now=now,
        )
    except OversightRefusedError as error:
        raise _oversight_refused(error) from error
    await session.commit()
    return GovernanceExceptionRead.model_validate(row).model_copy(
        update={"active": row.starts_at <= now < row.ends_at}
    )


@router.post("/decisions/exceptions/{exception_id}/revoke", response_model=GovernanceExceptionRead)
async def revoke_exception(
    exception_id: uuid.UUID, principal: Admin, session: SessionDep
) -> GovernanceExceptionRead:
    """It no longer holds from now; it is kept, and so is who revoked it."""
    try:
        row = await OversightService(session, principal.workspace_id).revoke_exception(
            exception_id, by=principal.user_id
        )
    except OversightRefusedError as error:
        raise _oversight_refused(error) from error
    if row is None:
        raise _gone("exception")
    await session.commit()
    return GovernanceExceptionRead.model_validate(row)


@router.get("/decisions/delegations", response_model=list[DelegationRead])
async def delegations(principal: Reader, session: SessionDep) -> list[DelegationRead]:
    """Every delegation, the latest first, each said active or not."""
    now = datetime.now(UTC)
    rows = await OversightService(session, principal.workspace_id).delegation_rows()
    return [
        DelegationRead.model_validate(r).model_copy(
            update={"active": r.revoked_at is None and r.starts_at <= now < r.ends_at}
        )
        for r in rows
    ]


@router.post(
    "/decisions/delegations",
    response_model=DelegationRead,
    status_code=status.HTTP_201_CREATED,
)
async def delegate(
    payload: DelegationCreate, principal: Approver, session: SessionDep
) -> DelegationRead:
    """Your authority to approve lent to a member, up to a risk, for a time
    — 90 days at most. Their votes for you count as yours, and keep both
    names. 422 when it cannot be lent as said."""
    now = datetime.now(UTC)
    try:
        row = await OversightService(session, principal.workspace_id).delegate(
            by=principal.user_id,
            to=payload.to,
            max_risk=payload.max_risk,
            starts_at=payload.starts_at or now,
            ends_at=payload.ends_at,
            reason=payload.reason,
            now=now,
        )
    except OversightRefusedError as error:
        raise _oversight_refused(error) from error
    await session.commit()
    return DelegationRead.model_validate(row).model_copy(
        update={"active": row.starts_at <= now < row.ends_at}
    )


@router.post("/decisions/delegations/{delegation_id}/revoke", response_model=DelegationRead)
async def revoke_delegation(
    delegation_id: uuid.UUID, principal: Reader, session: SessionDep
) -> DelegationRead:
    """Revoked by who lent it, or by an admin; kept."""
    try:
        row = await OversightService(session, principal.workspace_id).revoke_delegation(
            delegation_id,
            by=principal.user_id,
            anyones=principal.has(Permission.WORKSPACE_UPDATE),
        )
    except OversightRefusedError as error:
        raise _oversight_refused(error) from error
    if row is None:
        raise _gone("delegation")
    await session.commit()
    return DelegationRead.model_validate(row)


@router.get("/decisions/governance-history", response_model=list[GovernanceEventRead])
async def governance_history(
    principal: Reader,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[GovernanceEventRead]:
    """The governance trail, the latest first: the policy changed, an
    exception or a delegation granted or revoked, a decision escalated,
    waived or frozen — who, when, on what. The database refuses to rewrite
    it."""
    rows = await OversightService(session, principal.workspace_id).trail(limit=limit)
    return [GovernanceEventRead.model_validate(r) for r in rows]


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
    principal: Voter,
    session: SessionDep,
) -> DecisionRead:
    """A vote on the decision open on it, kept with who, when, why and its
    context. Rejecting, modifying and asking for changes say why. Modifying
    says where it should run, which actions are kept: a new revision, its
    risk read again, the earlier approvals void. `on_behalf_of`: cast with
    an approver's authority they delegated to you, else 403. 409 when
    nothing is open, or a freeze covers it."""
    if payload.on_behalf_of is None and not principal.has(Permission.INTENTION_APPROVE):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.PERMISSION_DENIED,
            f"Your role in this workspace ({principal.role.value}) does not allow "
            f"{Permission.INTENTION_APPROVE.value}.",
        )
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
            on_behalf_of=payload.on_behalf_of,
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
