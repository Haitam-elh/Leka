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


class Bundle(_Model):
    """Specialist agents sold together (LEKA-439): cheaper than each alone."""

    key: str
    name: Words
    agents: tuple[str, ...] = Field(min_length=2)
    monthly_price: int = Field(gt=0)


class AddOns(_Model):
    """Every agent: none in a plan — offered only once available."""

    available: bool
    agents: tuple[str, ...]
    # Each agent's monthly price, once decided: absent, never guessed.
    prices: dict[str, int] = Field(default_factory=dict)
    bundles: tuple[Bundle, ...] = ()


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
    """The catalogue LEKA ships — read once, checked when read."""
    return load()


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
    "Quote",
    "Words",
    "catalogue",
    "load",
    "quote",
]
