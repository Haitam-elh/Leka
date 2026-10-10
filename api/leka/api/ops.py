"""Operations, over HTTP (LEKA-408) — for a scraper and an operator, not for
the product's users.

    GET /ops/metrics   every metric, Prometheus text format
    GET /ops/health    every component — ok, degraded, down — said why;
                       503 when LEKA is down

Both take the metrics token as a bearer (LEKA_METRICS_TOKEN). No token
configured: both answer 404, as if they did not exist — operating data is not
for the internet. `/health` stays open: it is what a load balancer asks.
"""

from __future__ import annotations

import asyncio
import hmac
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel
from starlette.responses import Response as StarletteResponse

from leka.api.errors import ApiError
from leka.core.config import settings
from leka.core.errors import ErrorCode
from leka.ops import cached, components, observe_request, overall, render, watch

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ops", tags=["operations"])


def _operator(authorization: Annotated[str | None, Header()] = None) -> None:
    token = settings.metrics_token
    if token is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "Not found.")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), token.get_secret_value().encode()):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.NOT_AUTHENTICATED, "Not allowed.")


Operator = Annotated[None, Depends(_operator)]


class ComponentRead(BaseModel):
    name: str
    status: Literal["ok", "degraded", "down"]
    detail: str | None


class OpsHealthRead(BaseModel):
    status: Literal["ok", "degraded", "down"]
    components: list[ComponentRead]


@router.get(
    "/metrics",
    response_class=Response,
    summary="Every metric, as Prometheus reads them",
    responses={200: {"content": {"text/plain": {}}}},
)
async def metrics(_: Operator) -> Response:
    return Response(
        content=render(await cached()), media_type="text/plain; version=0.0.4; charset=utf-8"
    )


@router.get("/health", response_model=OpsHealthRead, summary="How every component stands")
async def ops_health(_: Operator, response: Response) -> OpsHealthRead:
    found = await components(await cached())
    said = overall(found)
    if said == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return OpsHealthRead(
        status=said,
        components=[ComponentRead(name=c.name, status=c.status, detail=c.detail) for c in found],
    )


async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[StarletteResponse]]
) -> StarletteResponse:
    """Every request counted, by its route's template — never its path: one
    series per route, not one per id, and no id in the metrics."""
    began = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        template = getattr(route, "path", None) or "unmatched"
        observe_request(request.method, template, status_code, time.perf_counter() - began)


async def watch_forever(interval: float) -> None:
    """The alerts, judged from the API process too: a worker that is down
    cannot report itself. Locked in Redis with the worker's job — one
    judgement a minute, whoever makes it."""
    while True:
        await asyncio.sleep(interval)
        try:
            await watch()
        except Exception:
            logger.exception("ops_watch_failed")
