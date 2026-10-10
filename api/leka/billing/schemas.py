"""What the billing module says over HTTP (LEKA-431)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from leka.billing.catalogue import Quote, Words
from leka.billing.models import EVENTS


class _Read(BaseModel):
    model_config = ConfigDict(frozen=True)


class PlanRead(_Read):
    key: str
    name: str
    self_service: bool
    recommended: bool
    audience: Words
    value: Words
    # Monthly and yearly, as checkout charges them; none for Enterprise.
    quotes: list[Quote]
    ai_credits_per_month: int | None
    ai_credits_provisional: bool
    ai_credits_contractual: bool
    managed_llm: bool
    own_llm: bool


class CoreAgentRead(_Read):
    key: str
    name: Words


class LaunchOfferRead(_Read):
    percent: int
    months: int
    open: bool
    ends_on: str | None
    stacks_with_annual: Literal[False] = False


class BookingRead(_Read):
    """Where an Enterprise prospect books a meeting — none until it is
    configured — and the contact path that always works."""

    url: str | None
    contact_url: str


class PricingRead(_Read):
    """The catalogue as the pricing page shows it: every price computed here,
    from catalogue.yaml — the page states none of its own."""

    version: str
    currency: str
    annual_discount_percent: int
    launch_offer: LaunchOfferRead
    core_agents: list[CoreAgentRead]
    plans: list[PlanRead]
    add_ons_available: bool
    capacity_any_time: bool
    automatic_overage: Literal[False] = False
    capacity_packs_available: bool
    booking: BookingRead


EventName = Literal[
    "page_viewed",
    "interval_selected",
    "plan_selected",
    "cta_clicked",
    "enterprise_booking_clicked",
    "enterprise_contact_clicked",
]
assert set(EventName.__args__) == set(EVENTS)  # type: ignore[attr-defined]


class SiteEventCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event: EventName
    page: Literal["pricing"] = "pricing"
    plan: Literal["free", "starter", "growth", "business", "enterprise"] | None = None
    interval: Literal["month", "year"] | None = None
    language: Literal["fr", "en"] | None = None


class SiteEventCount(_Read):
    event: str
    plan: str | None
    interval: str | None
    count: int = Field(ge=0)
