"""The pricing page's data, and what its visitors did (LEKA-431)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing.catalogue import INTERVALS, Catalogue, quote
from leka.billing.models import SiteEvent
from leka.billing.repository import SiteEventRepository
from leka.billing.schemas import (
    BookingRead,
    CoreAgentRead,
    LaunchOfferRead,
    PlanRead,
    PricingRead,
    SiteEventCount,
    SiteEventCreate,
)
from leka.governance import plan_credits


def pricing(
    offer: Catalogue, *, today: date, booking_url: str | None, contact_url: str
) -> PricingRead:
    """Every plan with its prices on each interval it is sold on — computed
    from the catalogue, as checkout will charge them."""
    plans = []
    for plan in offer.plans:
        quotes = (
            [
                quote(plan, interval, offer, today=today)
                for interval in INTERVALS
                if interval == "month" or plan.annual
            ]
            if plan.monthly_price is not None
            else []
        )
        allowance = plan.ai_credits_per_month
        # Metering's, never a second figure of the page's own (LEKA-430).
        monthly = None if allowance.contractual else plan_credits(plan.key)
        plans.append(
            PlanRead(
                key=plan.key,
                name=plan.name,
                self_service=plan.self_service,
                recommended=plan.recommended,
                audience=plan.audience,
                value=plan.value,
                quotes=quotes,
                ai_credits_per_month=monthly,
                ai_credits_provisional=allowance.provisional,
                ai_credits_contractual=allowance.contractual,
                managed_llm=plan.managed_llm,
                own_llm=plan.own_llm,
            )
        )
    launch = offer.launch_offer
    return PricingRead(
        version=offer.version,
        currency=offer.currency,
        annual_discount_percent=offer.annual_discount_percent,
        launch_offer=LaunchOfferRead(
            percent=launch.percent,
            months=launch.months,
            open=offer.launch_open(today),
            ends_on=launch.ends_on.isoformat() if launch.ends_on else None,
        ),
        core_agents=[CoreAgentRead(key=a.key, name=a.name) for a in offer.core_agents],
        plans=plans,
        add_ons_available=offer.add_ons.available,
        capacity_any_time=offer.capacity.purchase_any_time,
        capacity_packs_available=bool(offer.capacity.packs),
        booking=BookingRead(url=booking_url, contact_url=contact_url),
    )


async def record(session: AsyncSession, said: SiteEventCreate, *, at: datetime) -> None:
    """One thing a visitor did — what, on which plan and interval, when;
    never who, never from where."""
    SiteEventRepository(session).add(
        SiteEvent(
            event=said.event,
            page=said.page,
            plan=said.plan,
            interval=said.interval,
            language=said.language,
            at=at,
        )
    )
    await session.commit()


async def counts(session: AsyncSession, *, since: datetime) -> list[SiteEventCount]:
    """What visitors did since a moment, counted — LEKA's own analytics."""
    found = await SiteEventRepository(session).counts(since=since)
    return [SiteEventCount(event=e, plan=p, interval=i, count=n) for e, p, i, n in found]
