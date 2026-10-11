"""LEKA CORE's pricing, over HTTP — public, for the site's pricing page
(LEKA-431).

    GET  /pricing          every plan, its prices monthly and yearly as
                           checkout charges them, the launch offer, the AI
                           capacity, where an Enterprise prospect books a
                           meeting — computed from catalogue.yaml
    POST /pricing/events   what a visitor chose or clicked: 204 — anonymous,
                           held per address, nothing about who

No session: the page is the site's, open to anyone. Nothing here reads a
workspace.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status

from leka.api.dependencies import SessionDep
from leka.api.identity import client_ip
from leka.billing import PricingRead, SiteEventCreate, catalogue, pricing, record
from leka.core import ratelimit
from leka.core.config import settings

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.get("", response_model=PricingRead, summary="LEKA CORE's plans and prices")
async def read_pricing() -> PricingRead:
    return pricing(
        catalogue(),
        today=datetime.now(UTC).date(),
        booking_url=settings.sales_booking_url,
        contact_url=settings.sales_contact_url,
    )


@router.post(
    "/events",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="What a visitor of the pricing page chose or clicked",
)
async def record_event(said: SiteEventCreate, request: Request, session: SessionDep) -> Response:
    verdict = await ratelimit.consume(
        "site_events:ip", client_ip(request), ratelimit.SITE_EVENTS_PER_IP
    )
    if verdict.allowed:
        await record(session, said, at=datetime.now(UTC))
    # Over the limit: dropped, quietly — analytics never block a visitor.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
