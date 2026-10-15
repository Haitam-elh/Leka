"""LEKA CORE's commercial catalogue (LEKA-431, LEKA-446): its plans, their
prices, discounts and trial, what each includes — read from catalogue.yaml,
the one source of truth, and checked when it is read.

    quote(plan, interval)   what a plan costs on an interval, the discount
                            that applies — the annual one, or the launch
                            offer, never both — what is charged each period
                            and what it comes to per month; with a trial,
                            when the first charge falls

Pure: no database, no network. Amounts are integer cents, rounded half up
per unit price, so what the page shows is what checkout charges.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CATALOGUE_FILE = Path(__file__).resolve().parent / "catalogue.yaml"

Interval = Literal["month", "year"]
INTERVALS: tuple[Interval, ...] = ("month", "year")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Words(_Model):
    fr: str
    en: str


class Allowance(_Model):
    """A plan's monthly AI credits — a capacity unit, not tokens.

    How many is metering's to say (LEKA-430, `governance.plan_credits`,
    LEKA_PLAN_CREDITS): the page reads them from it, so it can never promise
    other than what a workspace gets. Only a contract says otherwise."""

    # A launch hypothesis, until metering (LEKA-430) measures real usage.
    provisional: bool = False
    # Set per contract (Enterprise).
    contractual: bool = False


class Monitoring(_Model):
    """What a plan watches for its workspace (LEKA-442). Every plan shows
    the states, their freshness and what covers them; watching proactively
    — alerts opened, deduplicated, kept to what the data supports — and
    telling (in LEKA, by e-mail) are a paid plan's. `provisional`: decided
    for the launch, to revisit."""

    proactive: bool
    alerts: tuple[Literal["in_app", "email"], ...] = ()
    contractual: bool = False
    provisional: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> Monitoring:
        if self.alerts and not self.proactive:
            msg = "alerts need proactive monitoring"
            raise ValueError(msg)
        return self


class Quotas(_Model):
    """What a plan holds (2026-10-14 — to validate): people, sources
    connected, standard analyses a month, alert rules, recurring workflows.
    None: no limit said; `contractual`: per contract."""

    users: int | None = Field(default=None, ge=0)
    sources: int | None = Field(default=None, ge=0)
    analyses: int | None = Field(default=None, ge=0)
    alert_rules: int | None = Field(default=None, ge=0)
    workflows: int | None = Field(default=None, ge=0)
    provisional: bool = False
    contractual: bool = False


class Plan(_Model):
    key: Literal["free", "starter", "growth", "business", "enterprise"]
    name: str
    # Cents a month, excluding VAT; None: priced per contract.
    monthly_price: int | None = Field(ge=0)
    self_service: bool
    recommended: bool = False
    audience: Words
    value: Words
    ai_credits_per_month: Allowance
    managed_llm: bool
    # Connecting the customer's own language model: Enterprise only.
    own_llm: bool
    launch_offer: bool
    annual: bool
    monitoring: Monitoring = Monitoring(proactive=False)
    # Days free before the first charge, a card required; None: none.
    trial_days: int | None = Field(default=None, gt=0)
    quotas: Quotas = Quotas()

    @model_validator(mode="after")
    def _coherent(self) -> Plan:
        if self.trial_days and not (self.self_service and self.monthly_price):
            msg = f"{self.key}: a trial needs a plan bought online"
            raise ValueError(msg)
        if self.self_service and self.monthly_price is None:
            msg = f"{self.key}: a self-service plan has a price"
            raise ValueError(msg)
        if self.own_llm and self.key != "enterprise":
            msg = f"{self.key}: connecting one's own model is Enterprise only"
            raise ValueError(msg)
        if (self.launch_offer or self.annual) and not self.monthly_price:
            msg = f"{self.key}: a discount needs a price to apply to"
            raise ValueError(msg)
        if self.monitoring.proactive and not (self.monthly_price or self.key == "enterprise"):
            msg = f"{self.key}: proactive monitoring is a paid plan's"
            raise ValueError(msg)
        return self


class LaunchOffer(_Model):
    percent: int = Field(gt=0, lt=100)
    months: int = Field(gt=0)
    intervals: tuple[Interval, ...]
    ends_on: date | None = None


Tier = Literal["standard", "specialized", "expert"]
PlanKey = Literal["free", "starter", "growth", "business", "enterprise"]


class SoldAgent(_Model):
    """An agent of the registry, on sale (LEKA-454): its tier, and the name
    the marketplace reference gives it — none when the reference has no
    equivalent, its price then a hypothesis to validate."""

    tier: Tier
    reference: str | None = None


class ReferenceAgent(_Model):
    """An agent of the marketplace reference (« Agents & Bundles », 14
    October): what it is called and costs there. A reference is not a
    proof: one no agent of the registry stands for is never sold, never
    shown available."""

    name: str
    category: str
    # None: named only by a bundle, priced nowhere — to arbitrate.
    tier: Tier | None = None


class Bundle(_Model):
    """Agents sold together, as the reference composes them: sold only when
    every one of them is (LEKA-454: « ne pas créer d'agent fantôme »)."""

    key: str
    name: Words
    value: Words | None = None
    # As the reference names them (its keys).
    members: tuple[str, ...] = Field(min_length=2)
    monthly_price: int = Field(gt=0)
    # Resolved when the catalogue is read: the registry's agents among its
    # members, those no agent stands for, and its members' prices alone —
    # None when one has no price: no saving shown that cannot be shown.
    agents: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    alone_price: int | None = None

    @property
    def sellable(self) -> bool:
        return not self.missing

    @property
    def savings_percent(self) -> int | None:
        if self.alone_price is None or self.monthly_price >= self.alone_price:
            return None
        return round(100 * (1 - self.monthly_price / self.alone_price))


class AddOns(_Model):
    """The agents (LEKA-454): LEKA's own capabilities are every plan's — its
    fundamental agents —, a plan may include some of the registry's agents,
    and every other is a monthly option, sold alone at its tier's price or
    in a bundle — once on sale, from the least plan."""

    available: bool
    # Prices a launch hypothesis: to validate, said so where shown.
    provisional: bool = False
    # The least plan that buys or runs an option: Free runs none.
    minimum_plan: Literal["starter", "growth", "business", "enterprise"] = "starter"
    # A tier's monthly price, cents.
    tiers: dict[Tier, int] = Field(default_factory=dict)
    # Each registry agent sold, its tier and its reference name.
    agents: dict[str, SoldAgent]
    # Included in a plan, without an option: the registry's agents each
    # plan runs as part of it.
    included: dict[PlanKey, tuple[str, ...]] = Field(default_factory=dict)
    # The marketplace reference, every agent it names.
    reference: dict[str, ReferenceAgent] = Field(default_factory=dict)
    bundles: tuple[Bundle, ...] = ()

    @property
    def prices(self) -> dict[str, int]:
        """Each agent's monthly price, cents."""
        return {
            key: self.tiers[agent.tier]
            for key, agent in self.agents.items()
            if agent.tier in self.tiers
        }

    def runtime_of(self, reference: str) -> str | None:
        """The registry's agent a reference agent is."""
        return next((key for key, a in self.agents.items() if a.reference == reference), None)

    def bundle(self, key: str) -> Bundle | None:
        return next((b for b in self.bundles if b.key == key), None)

    def included_in(self, plan: str) -> frozenset[str]:
        """The agents a plan runs as part of it — and every plan above it."""
        order = ("free", "starter", "growth", "business", "enterprise")
        if plan not in order:
            return frozenset()
        upto = order[: order.index(plan) + 1]
        return frozenset(k for p, keys in self.included.items() if p in upto for k in keys)

    @model_validator(mode="after")
    def _priced(self) -> AddOns:
        for agent in self.agents.values():
            if agent.tier not in self.tiers:
                msg = f"tier {agent.tier} has no price"
                raise ValueError(msg)
            if agent.reference is not None and agent.reference not in self.reference:
                msg = f"reference {agent.reference} is not in the reference"
                raise ValueError(msg)
        for plan, keys in self.included.items():
            unknown = [k for k in keys if k not in self.agents]
            if unknown:
                msg = f"plan {plan} includes agents not in the registry's: {unknown}"
                raise ValueError(msg)
        resolved = []
        for bundle in self.bundles:
            unknown = [m for m in bundle.members if m not in self.reference]
            if unknown:
                msg = f"bundle {bundle.key}: members not in the reference {unknown}"
                raise ValueError(msg)
            agents = tuple(a for m in bundle.members if (a := self.runtime_of(m)) is not None)
            missing = tuple(m for m in bundle.members if self.runtime_of(m) is None)
            tiers = [self.reference[m].tier for m in bundle.members]
            alone = (
                sum(self.tiers[t] for t in tiers if t is not None)
                if all(t is not None and t in self.tiers for t in tiers)
                else None
            )
            if alone is not None and bundle.monthly_price >= alone:
                msg = f"bundle {bundle.key}: no cheaper than its agents alone"
                raise ValueError(msg)
            resolved.append(
                bundle.model_copy(
                    update={"agents": agents, "missing": missing, "alone_price": alone}
                )
            )
        object.__setattr__(self, "bundles", tuple(resolved))
        return self


class Capacity(_Model):
    """The plan's, never sold apart (LEKA-446): no pack, no top-up."""

    # Never: at the limit, billable usage pauses until the plan is upgraded.
    automatic_overage: Literal[False]


class Catalogue(_Model):
    version: str
    currency: Literal["EUR"]
    annual_discount_percent: int = Field(gt=0, lt=100)
    launch_offer: LaunchOffer
    plans: tuple[Plan, ...]
    add_ons: AddOns
    capacity: Capacity

    @model_validator(mode="after")
    def _whole(self) -> Catalogue:
        keys = [p.key for p in self.plans]
        if keys != ["free", "starter", "growth", "business", "enterprise"]:
            msg = f"the five plans, in order: got {keys}"
            raise ValueError(msg)
        if sum(p.recommended for p in self.plans) > 1:
            msg = "one recommended plan at most"
            raise ValueError(msg)
        if "year" in self.launch_offer.intervals:
            msg = "the launch offer never stacks with the annual discount"
            raise ValueError(msg)
        return self

    def plan(self, key: str) -> Plan:
        for plan in self.plans:
            if plan.key == key:
                return plan
        raise KeyError(key)

    def launch_open(self, today: date) -> bool:
        ends = self.launch_offer.ends_on
        return ends is None or today <= ends


def load(path: Path = CATALOGUE_FILE) -> Catalogue:
    return Catalogue.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@cache
def catalogue() -> Catalogue:
    """The catalogue LEKA ships — read once, checked when read (its file
    looked up when read: a test gives its own, then clears the cache)."""
    return load(CATALOGUE_FILE)


# ── what a plan costs ───────────────────────────────────────────────────────


def _cents(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class Quote(_Model):
    """What a plan costs on an interval."""

    plan: str
    interval: Interval
    # The list price a month, before any discount.
    list_monthly: int
    # The discount that applies: annual, launch — one at most.
    discount: Literal["annual", "launch"] | None
    percent: int
    # What it comes to a month with the discount; charged each period.
    monthly: int
    charged: int
    # The launch offer: for how many months, then the list price.
    for_months: int | None
    then_monthly: int | None
    # A trial: its days, and the day `charged` is first charged — unless
    # cancelled before. None: charged the day it is bought.
    trial_days: int | None = None
    first_charge_on: date | None = None


def quote(
    plan: Plan,
    interval: Interval,
    offer: Catalogue,
    *,
    today: date,
    launch: bool = True,
    trial: bool = True,
) -> Quote:
    """What `plan` costs billed every `interval`: the annual discount on a
    year, the launch offer on a month when the plan and the date allow it
    and `launch` (the customer is eligible) — never both — and its trial
    when it has one and `trial` (the customer is eligible). Raises
    ValueError for a plan with no price, or an interval it is not sold on."""
    priced = _priced(plan, interval, offer, today=today, launch=launch)
    if not (trial and plan.trial_days):
        return priced
    return priced.model_copy(
        update={
            "trial_days": plan.trial_days,
            "first_charge_on": today + timedelta(days=plan.trial_days),
        }
    )


def _priced(
    plan: Plan, interval: Interval, offer: Catalogue, *, today: date, launch: bool
) -> Quote:
    if plan.monthly_price is None:
        msg = f"{plan.key} is priced per contract"
        raise ValueError(msg)
    price = Decimal(plan.monthly_price)
    if interval == "year":
        if not plan.annual:
            msg = f"{plan.key} is not sold yearly"
            raise ValueError(msg)
        percent = offer.annual_discount_percent
        monthly = _cents(price * (100 - percent) / 100)
        return Quote(
            plan=plan.key,
            interval="year",
            list_monthly=plan.monthly_price,
            discount="annual",
            percent=percent,
            monthly=monthly,
            charged=monthly * 12,
            for_months=None,
            then_monthly=None,
        )
    eligible = (
        launch
        and plan.launch_offer
        and "month" in offer.launch_offer.intervals
        and offer.launch_open(today)
    )
    if not eligible:
        return Quote(
            plan=plan.key,
            interval="month",
            list_monthly=plan.monthly_price,
            discount=None,
            percent=0,
            monthly=plan.monthly_price,
            charged=plan.monthly_price,
            for_months=None,
            then_monthly=None,
        )
    percent = offer.launch_offer.percent
    monthly = _cents(price * (100 - percent) / 100)
    return Quote(
        plan=plan.key,
        interval="month",
        list_monthly=plan.monthly_price,
        discount="launch",
        percent=percent,
        monthly=monthly,
        charged=monthly,
        for_months=offer.launch_offer.months,
        then_monthly=plan.monthly_price,
    )


__all__ = [
    "CATALOGUE_FILE",
    "INTERVALS",
    "AddOns",
    "Allowance",
    "Capacity",
    "Catalogue",
    "Interval",
    "LaunchOffer",
    "Plan",
    "Quotas",
    "Quote",
    "Tier",
    "Words",
    "catalogue",
    "load",
    "quote",
]
