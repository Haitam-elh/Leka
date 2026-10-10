"""Carrying out what was approved, over HTTP (LEKA-391).

    GET    /action-endpoints                  the systems LEKA may act through
    POST   /action-endpoints                  one authorized — its secret shown once
    PATCH  /action-endpoints/{id}             changed, enabled, disabled
    DELETE /action-endpoints/{id}
    GET    /intentions/{id}/plans             every plan, the latest first
    POST   /intentions/{id}/plan              the plan of its approved decision
    POST   /intentions/{id}/plan/start        checked, then run — or scheduled
    POST   /intentions/{id}/plan/cancel       stopped, saying why
    POST   /intentions/{id}/plan/steps/{step_id}/report   a person's word on a step

Reading needs `intention:read`; planning, starting, cancelling, reporting
`intention:approve`; the authorized systems `workspace:update`. A system is
called by the job, once the route has committed.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, Target, audit_as, require_permission
from leka.intentions import (
    ActionEndpointCreate,
    ActionEndpointCreated,
    ActionEndpointRead,
    ActionEndpointUpdate,
    ActionService,
    EndpointService,
    IllegalTransitionError,
    IntentionArchivedError,
    IntentionPlanRead,
    PlanCancelRequest,
    PlanRefusedError,
    PlanStartRequest,
    StepReportRequest,
    endpoint_read,
    queue_plan,
)

router = APIRouter(tags=["actions"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]
Admin = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))]

STATUSES = {
    "not_approved": status.HTTP_409_CONFLICT,
    "already_planned": status.HTTP_409_CONFLICT,
    "nothing_planned": status.HTTP_409_CONFLICT,
    "not_cancellable": status.HTTP_409_CONFLICT,
    "not_awaiting": status.HTTP_409_CONFLICT,
    "checks_failed": status.HTTP_409_CONFLICT,
}


def _missing(what: str = "intention") -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"No such {what}.")


def _refused(error: Exception) -> ApiError:
    """What cannot be done now — its code, and the checks that failed, in
    `details` for the interface to say them."""
    if isinstance(error, PlanRefusedError):
        details = [FieldError(field="refusal", message=error.code)] + [
            FieldError(field=f"check.{check['code']}", message="failed") for check in error.failed
        ]
        return ApiError(
            STATUSES.get(error.code, status.HTTP_409_CONFLICT),
            ErrorCode.CONFLICT,
            str(error),
            details=details,
        )
    return ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, str(error))


REFUSED = (PlanRefusedError, IllegalTransitionError, IntentionArchivedError)


# ── the authorized systems ───────────────────────────────────────────────────


@router.get("/action-endpoints", response_model=list[ActionEndpointRead])
async def endpoints(principal: Reader, session: SessionDep) -> list[ActionEndpointRead]:
    return await EndpointService(session, principal.workspace_id).list()


@router.post(
    "/action-endpoints",
    response_model=ActionEndpointCreated,
    status_code=status.HTTP_201_CREATED,
)
async def authorize(
    payload: ActionEndpointCreate, principal: Admin, session: SessionDep
) -> ActionEndpointCreated:
    """A system LEKA may call for these actions, in these environments. Its
    signing secret is in the answer, this once."""
    row, secret = await EndpointService(session, principal.workspace_id).create(
        name=payload.name,
        url=str(payload.url),
        actions=payload.actions,
        environments=payload.environments,
        targets=payload.targets,
        by=principal.user_id,
    )
    audit_as(
        session,
        principal,
        "action",
        "action_endpoint.authorized",
        target=Target("action_endpoint", row.id, payload.name),
        detail={"actions": list(payload.actions), "environments": list(payload.environments)},
    )
    await session.commit()
    return ActionEndpointCreated(endpoint=endpoint_read(row), secret=secret)


@router.patch("/action-endpoints/{endpoint_id}", response_model=ActionEndpointRead)
async def change(
    endpoint_id: uuid.UUID, payload: ActionEndpointUpdate, principal: Admin, session: SessionDep
) -> ActionEndpointRead:
    service = EndpointService(session, principal.workspace_id)
    row = await service.get(endpoint_id)
    if row is None:
        raise _missing("endpoint")
    await service.update(row, payload.model_dump(exclude_none=True))
    audit_as(
        session,
        principal,
        "action",
        "action_endpoint.changed",
        target=Target("action_endpoint", endpoint_id, row.name),
        detail={"changed": sorted(payload.model_dump(exclude_none=True))},
    )
    await session.commit()
    return endpoint_read(row)


@router.delete("/action-endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(endpoint_id: uuid.UUID, principal: Admin, session: SessionDep) -> Response:
    service = EndpointService(session, principal.workspace_id)
    row = await service.get(endpoint_id)
    if row is None:
        raise _missing("endpoint")
    audit_as(
        session,
        principal,
        "action",
        "action_endpoint.removed",
        target=Target("action_endpoint", endpoint_id, row.name),
    )
    await service.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── plans ────────────────────────────────────────────────────────────────────


def _plan_audited(
    session: AsyncSession,
    principal: Principal,
    action: str,
    intention_id: uuid.UUID,
    plan_id: uuid.UUID,
    **detail: object,
) -> None:
    audit_as(
        session,
        principal,
        "action",
        action,
        target=Target("intention", intention_id),
        detail={"plan": str(plan_id), **{k: v for k, v in detail.items() if v is not None}},
    )


async def _queued(service: ActionService, principal: Principal) -> None:
    for plan_id in service.to_queue:
        await queue_plan(principal.workspace_id, plan_id)


@router.get("/intentions/{intention_id}/plans", response_model=list[IntentionPlanRead])
async def plans(
    intention_id: uuid.UUID, principal: Reader, session: SessionDep
) -> list[IntentionPlanRead]:
    found = await ActionService(session, principal.workspace_id).plans(intention_id)
    if found is None:
        raise _missing()
    return found


@router.post(
    "/intentions/{intention_id}/plan",
    response_model=IntentionPlanRead,
    status_code=status.HTTP_201_CREATED,
)
async def plan(
    intention_id: uuid.UUID, principal: Approver, session: SessionDep
) -> IntentionPlanRead:
    """The plan of its approved decision — of what did not succeed, after
    a failure: who runs each action, an authorized system or a person."""
    try:
        made = await ActionService(session, principal.workspace_id).plan(
            intention_id, by=principal.user_id
        )
    except REFUSED as error:
        raise _refused(error) from error
    if made is None:
        raise _missing()
    _plan_audited(session, principal, "action_plan.created", intention_id, made.id)
    await session.commit()
    return made


@router.post("/intentions/{intention_id}/plan/start", response_model=IntentionPlanRead)
async def start(
    intention_id: uuid.UUID, payload: PlanStartRequest, principal: Approver, session: SessionDep
) -> IntentionPlanRead:
    """Checked, then run now — or scheduled at `scheduled_for`. 409, the
    failing checks in `details`, when what must hold does not."""
    service = ActionService(session, principal.workspace_id)
    try:
        started = await service.start(
            intention_id,
            by=principal.user_id,
            at=payload.scheduled_for,
            timezone=payload.timezone,
        )
    except PlanRefusedError as error:
        # The checks it failed are kept with the plan.
        await session.commit()
        raise _refused(error) from error
    except REFUSED as error:
        raise _refused(error) from error
    if started is None:
        raise _missing()
    _plan_audited(
        session,
        principal,
        "action_plan.started",
        intention_id,
        started.id,
        scheduled_for=payload.scheduled_for.isoformat() if payload.scheduled_for else None,
    )
    await session.commit()
    await _queued(service, principal)
    return started


@router.post("/intentions/{intention_id}/plan/cancel", response_model=IntentionPlanRead)
async def cancel(
    intention_id: uuid.UUID, payload: PlanCancelRequest, principal: Approver, session: SessionDep
) -> IntentionPlanRead:
    """Stopped: before it runs, the intention approved again; while it
    runs, what has not started cancelled."""
    try:
        stopped = await ActionService(session, principal.workspace_id).cancel(
            intention_id, by=principal.user_id, reason=payload.reason
        )
    except REFUSED as error:
        raise _refused(error) from error
    if stopped is None:
        raise _missing()
    _plan_audited(
        session, principal, "action_plan.cancelled", intention_id, stopped.id, reason=payload.reason
    )
    await session.commit()
    return stopped


@router.post(
    "/intentions/{intention_id}/plan/steps/{step_id}/report", response_model=IntentionPlanRead
)
async def report(
    intention_id: uuid.UUID,
    step_id: uuid.UUID,
    payload: StepReportRequest,
    principal: Approver,
    session: SessionDep,
) -> IntentionPlanRead:
    """A step waiting on a person — theirs, or a system's that accepted the
    work — said done or failed, with what shows it."""
    service = ActionService(session, principal.workspace_id)
    try:
        reported = await service.report(
            intention_id,
            step_id,
            outcome=payload.outcome,
            note=payload.note,
            link=str(payload.link) if payload.link else None,
            by=principal.user_id,
        )
    except REFUSED as error:
        raise _refused(error) from error
    if reported is None:
        raise _missing("step")
    _plan_audited(
        session,
        principal,
        "action_step.reported",
        intention_id,
        reported.id,
        step=str(step_id),
        outcome=payload.outcome,
    )
    await session.commit()
    await _queued(service, principal)
    return reported
