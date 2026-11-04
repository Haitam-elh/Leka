"""A workspace's own language model, over HTTP (LEKA-394) — Paramètres > Le
modèle de votre entreprise, under an Enterprise contract (LEKA-530).

    GET    /models                 whether its contract brings a model of its
                                   own, the providers it may bring, its own
                                   model if it set one
    PUT    /models/settings        bring its own model (key kept encrypted,
                                   never sent back) — 403 on a plan that does
                                   not bring one · DELETE: back to LEKA's, on
                                   any plan
    POST   /models/settings/test   asked a few words: did it answer

Never LEKA's models, their prices, the tokens or the cost of what was asked:
the LEKA team assigns a model to each agent (agents/models.yaml) and reads
what it used internally (python -m leka.metering.cli usage) — customers buy
what the agents deliver, not a catalogue of models.

Reading takes `workspace:read`; changing or testing `workspace:update`.

A route validates, calls one service, and returns (architecture rule 6).
Permissions come from a FastAPI dependency, never an `if` in the body
(rule 5). The workspace is read from the session, never from the path or the
payload (rule 3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Response, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    ModelProviderRead,
    ModelSettingError,
    ModelSettings,
    ModelSettingsRead,
    ModelTestRead,
    OwnModelNotOfferedError,
    WorkspaceModel,
    WorkspaceModelRead,
    WorkspaceModelUpdate,
)
from leka.capabilities.gateway.workspace import Change
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission

router = APIRouter(prefix="/models", tags=["models"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Admin = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))]


def own_read(row: WorkspaceModel) -> WorkspaceModelRead:
    return WorkspaceModelRead(
        provider=row.provider,
        model=row.model,
        base_url=row.base_url,
        api_version=row.api_version,
        key_hint=row.key_hint,
        enabled=row.enabled,
        exclusive=row.exclusive,
        status=cast(Literal["untested", "ok", "failed"], row.status),
        status_detail=row.status_detail,
        tested_at=row.tested_at,
        changed_at=row.changed_at,
    )


async def _overview(service: ModelSettings) -> ModelSettingsRead:
    seen = await service.overview()
    return ModelSettingsRead(
        offered=seen.offered,
        providers=[
            ModelProviderRead(
                name=o.name,
                title=o.title,
                needs=sorted(o.needs),
                default_model=o.default_model,
            )
            for o in seen.providers
        ],
        own=own_read(seen.own) if seen.own is not None else None,
    )


@router.get("", response_model=ModelSettingsRead)
async def gateway(principal: Reader, session: SessionDep) -> ModelSettingsRead:
    return await _overview(ModelSettings(session, principal.workspace_id))


@router.put("/settings", response_model=ModelSettingsRead)
async def save(
    payload: WorkspaceModelUpdate, principal: Admin, session: SessionDep
) -> ModelSettingsRead:
    service = ModelSettings(session, principal.workspace_id)
    try:
        await service.save(
            Change(
                provider=payload.provider,
                model=payload.model.strip() if payload.model else None,
                base_url=str(payload.base_url).rstrip("/") if payload.base_url else None,
                api_version=payload.api_version,
                api_key=payload.api_key.get_secret_value().strip() if payload.api_key else None,
                enabled=payload.enabled,
                exclusive=payload.exclusive,
            ),
            by=principal.user_id,
            now=datetime.now(UTC),
        )
    except OwnModelNotOfferedError as refused:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, ErrorCode.PLAN_REQUIRED, str(refused)
        ) from refused
    except ModelSettingError as refused:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            str(refused),
            details=[FieldError(field=refused.field, message=str(refused))],
        ) from refused
    await session.commit()
    return await _overview(service)


@router.delete("/settings", status_code=status.HTTP_204_NO_CONTENT)
async def remove(principal: Admin, session: SessionDep) -> Response:
    if not await ModelSettings(session, principal.workspace_id).remove():
        raise ApiError(
            status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No model of the workspace's own."
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/settings/test", response_model=ModelTestRead)
async def test(principal: Admin, session: SessionDep) -> ModelTestRead:
    tested = await ModelSettings(session, principal.workspace_id).test()
    await session.commit()
    return ModelTestRead(
        ok=tested.ok,
        detail=tested.detail,
        latency_ms=tested.latency_ms,
        model=tested.model,
        version=tested.version,
    )
