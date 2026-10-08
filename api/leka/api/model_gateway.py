"""The language model of a workspace, over HTTP (LEKA-394) — Paramètres >
Modèle de langage.

    GET    /models                 what answers here: LEKA's default, its
                                   fallbacks, the providers one may bring,
                                   the workspace's own model, the order
    PUT    /models/settings        bring its own model (key kept encrypted,
                                   never sent back) · DELETE: back to LEKA's
    POST   /models/settings/test   asked a few words: did it answer
    GET    /models/usage           calls, tokens, cost — LEKA's and its own

Reading takes `workspace:read`; changing or testing `workspace:update`.

A route validates, calls one service, and returns (architecture rule 6).
Permissions come from a FastAPI dependency, never an `if` in the body
(rule 5). The workspace is read from the session, never from the path or the
payload (rule 3).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Response, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    ModelBreakdownRead,
    ModelCallRead,
    ModelDayRead,
    ModelGatewayRead,
    ModelPriceRead,
    ModelProfileRead,
    ModelProviderRead,
    ModelPurposeRead,
    ModelRouteRead,
    ModelSettingError,
    ModelSettings,
    ModelTallyRead,
    ModelTestRead,
    ModelUsageRead,
    WorkspaceModel,
    WorkspaceModelRead,
    WorkspaceModelUpdate,
    model_usage,
)
from leka.capabilities.gateway import Price, Profile, profile
from leka.capabilities.gateway.usage import Tally
from leka.capabilities.gateway.workspace import Change
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission

router = APIRouter(prefix="/models", tags=["models"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Admin = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))]


def _price(price: Price | None) -> ModelPriceRead | None:
    if price is None:
        return None
    return ModelPriceRead(
        since=price.since.isoformat(),
        per_million_in=price.per_million_in,
        per_million_out=price.per_million_out,
    )


def profile_read(found: Profile, now: datetime) -> ModelProfileRead:
    today = found.price(now)
    coming = [p for p in found.prices if p.since > now.date()]
    return ModelProfileRead(
        provider=found.provider,
        model=found.model,
        title=found.title,
        context=found.context,
        output=found.output,
        structured=found.structured,
        tools=found.tools,
        quality=found.quality,
        speed=found.speed,
        price=_price(today),
        next_price=_price(min(coming, key=lambda p: p.since) if coming else None),
        known=found.known,
    )


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


async def _overview(service: ModelSettings) -> ModelGatewayRead:
    now = datetime.now(UTC)
    seen = await service.overview()
    return ModelGatewayRead(
        default=profile_read(seen.default, now),
        default_ready=seen.default_ready,
        fallbacks=[profile_read(p, now) for p in seen.fallbacks],
        providers=[
            ModelProviderRead(
                name=o.name,
                title=o.title,
                needs=sorted(o.needs),
                default_model=o.default_model,
                leka_holds=o.leka_holds,
                models=[profile_read(p, now) for p in o.models],
            )
            for o in seen.offered
        ],
        own=own_read(seen.own) if seen.own is not None else None,
        answering=[
            ModelRouteRead(
                provider=r.endpoint.provider,
                model=r.profile.model,
                title=r.profile.title,
                owner=cast(Literal["leka", "workspace"], r.endpoint.owner),
                why=cast(Literal["own", "default", "fallback", "alternative"], r.why),
            )
            for r in seen.routing.routes
        ],
        ready=bool(seen.routing.routes),
    )


@router.get("", response_model=ModelGatewayRead)
async def gateway(principal: Reader, session: SessionDep) -> ModelGatewayRead:
    return await _overview(ModelSettings(session, principal.workspace_id))


@router.put("/settings", response_model=ModelGatewayRead)
async def save(
    payload: WorkspaceModelUpdate, principal: Admin, session: SessionDep
) -> ModelGatewayRead:
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


def _tally(tally: Tally) -> ModelTallyRead:
    return ModelTallyRead(
        calls=tally.calls,
        failed=tally.failed,
        tokens_in=tally.tokens_in,
        tokens_out=tally.tokens_out,
        cost_usd=round(tally.cost_usd, 6),
        unpriced=tally.unpriced,
        average_latency_ms=round(tally.latency_ms / tally.calls) if tally.calls else 0,
    )


@router.get("/usage", response_model=ModelUsageRead)
async def usage(
    principal: Reader,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=180)] = 30,
) -> ModelUsageRead:
    now = datetime.now(UTC)
    found = await model_usage(session, principal.workspace_id, now=now, days=days)
    start = (now - timedelta(days=days - 1)).date()
    by_day = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        tally = found.by_day.get(day, Tally())
        by_day.append(
            ModelDayRead(
                day=day,
                calls=tally.calls,
                failed=tally.failed,
                tokens=tally.tokens_in + tally.tokens_out,
                cost_usd=round(tally.cost_usd, 6),
            )
        )
    return ModelUsageRead(
        days=days,
        total=_tally(found.total),
        previous=_tally(found.previous),
        leka=_tally(found.by_owner.get("leka", Tally())),
        own=_tally(found.by_owner.get("workspace", Tally())),
        fallbacks=found.fallbacks,
        by_day=by_day,
        by_model=[
            ModelBreakdownRead(
                provider=provider,
                model=model,
                title=profile(provider, model).title,
                tally=_tally(tally),
            )
            for (provider, model), tally in sorted(
                found.by_model.items(), key=lambda item: -item[1].calls
            )
        ],
        by_purpose=[
            ModelPurposeRead(purpose=purpose, tally=_tally(tally))
            for purpose, tally in sorted(found.by_purpose.items(), key=lambda item: -item[1].calls)
        ],
        latest=[ModelCallRead.model_validate(call) for call in found.latest],
    )
