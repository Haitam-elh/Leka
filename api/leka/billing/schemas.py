"""What the billing module says over HTTP (LEKA-431)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

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
    # Days free before the first charge, a card required; None: none.
    trial_days: int | None


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
    plans: list[PlanRead]
    add_ons_available: bool
    # The AI capacity is the plan's: never sold apart, never an overage.
    automatic_overage: Literal[False] = False
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


# ── paying ──────────────────────────────────────────────────────────────────


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan: Literal["starter", "growth", "business"]
    interval: Literal["month", "year"]


class CheckoutRead(_Read):
    """Where to pay — Stripe's page — and what will be charged, as the
    pricing page says it."""

    url: str
    quote: Quote | None


class PortalRead(_Read):
    url: str


class SubscriptionRead(_Read):
    """The workspace's subscription, as Stripe last said it."""

    available: bool = Field(description="Stripe is configured here: plans can be bought.")
    plan: str
    interval: str | None
    status: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    launch_offer_available: bool
    trial_available: bool = Field(description="Never subscribed here: a plan's trial may be had.")
    last_invoice: str | None
    has_customer: bool


# ── agents and bundles (2026-10-14) ─────────────────────────────────────────


class AgentOfferRead(_Read):
    """An agent as it is sold: its tier and price, whether this workspace owns
    it, and why it may not run it."""

    key: str
    title: str
    summary: str
    category: str
    tier: str
    monthly_price: int = Field(description="Cents a month, excluding VAT.")
    owned: bool
    why: str | None = Field(description="plan_required, not_owned — none when it may run it.")
    bundles: list[str] = Field(description="The bundles it comes in.")


class BundleOfferRead(_Read):
    key: str
    name: Words
    value: Words | None
    agents: list[str]
    monthly_price: int
    alone_price: int = Field(description="Its agents bought one by one, cents a month.")
    discount_percent: int
    owned: bool


class AddOnsRead(_Read):
    """What is sold besides a plan: agents, alone or in bundles — and where
    this workspace stands."""

    available: bool
    provisional: bool = Field(description="Prices to validate: said so where shown.")
    currency: str
    minimum_plan: str = Field(description="The least plan that runs an agent.")
    plan: str
    runs_agents: bool = Field(description="Its plan runs agents, or LEKA granted every one.")
    every: bool = Field(description="LEKA granted it every agent (its team's, for tests).")
    agents: list[AgentOfferRead]
    bundles: list[BundleOfferRead]


class AddOnCheckoutCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["agent", "bundle"]
    key: str = Field(max_length=100)
    # Opened from an intention's decision: the agents to launch once paid.
    intention_id: uuid.UUID | None = None
    launch: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=3)
    # Where Stripe sends the person back: the intention's decision, or the
    # new home's thread (2026-10-14) — a choice, never an address.
    back: Literal["intention", "home"] = "intention"


class EntitlementRead(_Read):
    """What a workspace owns: an agent, a bundle, or every one."""

    key: str
    kind: Literal["agent", "bundle", "all"]
    origin: Literal["purchase", "grant"]
    started_at: datetime
    agents: list[str] = Field(description="The agents it gives.")
