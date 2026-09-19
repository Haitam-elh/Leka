"""Health endpoint. The only route that exists before the modules do."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from leka.core.health import check_backing_services

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    services: dict[str, bool]


@router.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    """Report whether the API can reach PostgreSQL and Redis.

    503 when a backing service is down, so a load balancer takes this
    instance out of rotation instead of sending it traffic it cannot serve.
    """
    services = await check_backing_services()
    healthy = all(services.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if healthy else "degraded", services=services)
