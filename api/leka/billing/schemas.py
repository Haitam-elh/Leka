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


class QuotasRead(_Read):
    """What a plan holds (LEKA-466): people, sources connected, standard
    analyses a month, alert rules, recurring workflows. None: no limit said;
    `contractual`: per contract; `provisional`: to validate."""

    users: int | None
    sources: int | None
    analyses: int | None
    alert_rules: int | None
    workflows: int | None
    provisional: bool
    contractual: bool


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
    quotas: QuotasRead


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
    # Opened from an intention (LEKA-458): back to it once paid.
    intention_id: uuid.UUID | None = None


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
    why: str | None = Field(
        description="not_for_sale, plan_required, not_owned — none when it may run it."
    )
    bundles: list[str] = Field(description="The bundles it comes in.")
    reference: str | None = Field(
        default=None, description="Its name in the marketplace reference (LEKA-454)."
    )
    included: bool = Field(default=False, description="Its plan runs it, without an option.")
    market: str | None = Field(
        default=None,
        description="Its category in the marketplace (the reference's: product, architecture, "
        "testing, incident, security, performance, frontend, mobile…) — none outside it.",
    )
    included_from: str | None = Field(
        default=None,
        description="The least plan that includes it, whatever this workspace's plan.",
    )


class BundleMemberRead(_Read):
    """An agent a bundle names (LEKA-454): the registry's agent standing for
    it — none when no agent does yet, the bundle then not sold."""

    key: str
    name: str
    agent: str | None
    monthly_price: int | None = Field(description="Its reference price; none when unpriced.")


class BundleOfferRead(_Read):
    key: str
    name: Words
    value: Words | None
    agents: list[str]
    monthly_price: int
    alone_price: int | None = Field(
        description="Its members bought one by one, cents a month — none when one is unpriced."
    )
    discount_percent: int | None = Field(
        description="Computed from the members' prices; none when it cannot be shown."
    )
    owned: bool
    sellable: bool = Field(default=True, description="Every member an agent of the registry.")
    members: list[BundleMemberRead] = Field(default_factory=list)


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
    dedicated: list[str] = Field(
        default_factory=list,
        description="The agents made for this organisation, assigned by LEKA (2026-10-25): "
        "its own, never sold, never priced.",
    )


class AddOnCheckoutCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # « agents », « bundles »: several bought together, `key` their keys
    # comma-separated (LEKA-458, LEKA-500).
    kind: Literal["agent", "bundle", "agents", "bundles"]
    key: str = Field(max_length=400)
    # Opened from an intention's decision: the agents to launch once paid.
    intention_id: uuid.UUID | None = None
    launch: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=3)


class EntitlementRead(_Read):
    """What a workspace owns: an agent, a bundle, or every one."""

    key: str
    kind: Literal["agent", "bundle", "all"]
    origin: Literal["purchase", "grant"]
    started_at: datetime
    agents: list[str] = Field(description="The agents it gives.")
    subscription: str | None = Field(
        default=None, description="Bought: its Stripe subscription, to cancel or renew."
    )
    cancel_at_period_end: bool = Field(
        default=False, description="Cancelled: kept until current_period_end, then not renewed."
    )
    current_period_end: datetime | None = Field(
        default=None, description="When its paid period ends, as Stripe last said it."
    )
