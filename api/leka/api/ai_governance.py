"""The workspace's AI, governed, over HTTP (LEKA-406): its controls, and
what each did.

    GET    /governance/ai/controls          every control, on or off
    POST   /governance/ai/controls          created
    PUT    /governance/ai/controls/{id}     changed — its kind kept
    DELETE /governance/ai/controls/{id}     removed; what it did stays
    GET    /governance/ai/events            what the controls did, the latest first
    GET    /governance/ai/calls             the model calls, whom each was for

Reading the controls is any member's — what they may ask a model is theirs
to know; changing one takes `policy:manage`; what the controls did and the
calls made, `access:read`. Runs held for approval are approved or rejected
where they are: /agent-runs/{id}/approve · /reject. The workspace is the
session's (rule 3).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import ModelCallRead, model_calls
from leka.core.errors import ErrorCode, FieldError
from leka.governance import (
    AIControl,
    AIControlEventRead,
    AIControlRead,
    AIControlService,
    AIControlUpdate,
    ControlError,
    ControlInput,
    Permission,
    Principal,
    control_of_row,
    require_permission,
)

router = APIRouter(prefix="/governance/ai", tags=["governance"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Auditor = Annotated[Principal, Depends(require_permission(Permission.ACCESS_READ))]
Manager = Annotated[Principal, Depends(require_permission(Permission.POLICY_MANAGE))]
Outcome = Literal[
    "refused", "limited", "redacted", "blocked", "flagged", "held", "approved", "rejected"
]


def _read(row: AIControl) -> AIControlRead:
    control = control_of_row(row)
    return AIControlRead(
        id=row.id,
        updated_at=row.updated_at,
        name=row.name,
        description=row.description,
        kind=control.kind,
        purposes=list(control.purposes),
        roles=sorted(control.roles),
        enabled=row.enabled,
        providers=sorted(control.providers),
        owners=sorted(control.owners),
        block=control.block,
        period=control.period,
        per=control.per,
        max_calls=control.max_calls,
        max_tokens=control.max_tokens,
        max_cost_usd=control.max_cost_usd,
        detect=sorted(control.detect),
        on_finding=control.on_finding,
        risk_at_least=control.risk_at_least,
    )


def _input(body: AIControlUpdate) -> ControlInput:
    config: dict[str, object] = {
        "providers": body.providers,
        "owners": list(body.owners),
        "block": body.block,
        "period": body.period,
        "per": body.per,
        "max_calls": body.max_calls,
        "max_tokens": body.max_tokens,
        "max_cost_usd": body.max_cost_usd,
        "detect": list(body.detect),
        "on_finding": body.on_finding,
        "risk_at_least": body.risk_at_least,
    }
    return ControlInput(
        name=body.name,
        kind=body.kind,
        config=config,
        purposes=body.purposes,
        roles=body.roles,
        enabled=body.enabled,
        description=body.description,
    )


def _invalid(error: ControlError) -> ApiError:
    return ApiError(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_FAILED,
        str(error),
        details=[FieldError(field=error.field, message=str(error))],
    )


def _missing() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such control.")


@router.get("/controls", response_model=list[AIControlRead], summary="The workspace's AI controls")
async def controls(session: SessionDep, principal: Reader) -> list[AIControlRead]:
    return [_read(r) for r in await AIControlService(session, principal.workspace_id).controls()]


@router.post(
    "/controls",
    response_model=AIControlRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an AI control",
)
async def create_control(
    body: AIControlUpdate, session: SessionDep, principal: Manager
) -> AIControlRead:
    """In force from the next model call. 422 when it cannot be, said which
    field and why."""
    try:
        row = await AIControlService(session, principal.workspace_id).save(
            _input(body), by=principal.user_id
        )
    except ControlError as error:
        raise _invalid(error) from error
    assert row is not None
    return _read(row)


@router.put("/controls/{control_id}", response_model=AIControlRead, summary="Change an AI control")
async def update_control(
    control_id: uuid.UUID, body: AIControlUpdate, session: SessionDep, principal: Manager
) -> AIControlRead:
    try:
        row = await AIControlService(session, principal.workspace_id).save(
            _input(body), by=principal.user_id, control_id=control_id
        )
    except ControlError as error:
        raise _invalid(error) from error
    if row is None:
        raise _missing()
    return _read(row)


@router.delete(
    "/controls/{control_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an AI control",
)
async def delete_control(
    control_id: uuid.UUID, session: SessionDep, principal: Manager
) -> Response:
    if not await AIControlService(session, principal.workspace_id).delete(
        control_id, by=principal.user_id
    ):
        raise _missing()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/events", response_model=list[AIControlEventRead], summary="What the AI controls did")
async def events(
    session: SessionDep,
    principal: Auditor,
    outcome: Annotated[Outcome | None, Query()] = None,
    run_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AIControlEventRead]:
    rows = await AIControlService(session, principal.workspace_id).events(
        outcome=outcome, run_id=run_id, limit=limit
    )
    return [AIControlEventRead.model_validate(r) for r in rows]


@router.get(
    "/calls", response_model=list[ModelCallRead], summary="The model calls, whom each was for"
)
async def calls(
    session: SessionDep,
    principal: Auditor,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    run_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ModelCallRead]:
    rows = await model_calls(
        session, principal.workspace_id, user_id=user_id, run_id=run_id, limit=limit
    )
    return [ModelCallRead.model_validate(r) for r in rows]
