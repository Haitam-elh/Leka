"""LEKA CORE's commercial catalogue and what each plan costs (LEKA-431,
LEKA-446) — pure, and over HTTP.

What these protect:
- The catalogue LEKA ships is whole and coherent: five plans in order,
  Growth the one recommended, with a 14-day trial; no agent in any plan —
  every agent an add-on, none on sale until available; connecting one's
  own model only on Enterprise, priced per contract and never self-service;
  AI credits a number marked provisional (Enterprise: by contract); no AI
  capacity sold apart, never an automatic overage charge. A catalogue that
  breaks a rule — the launch offer on yearly billing, own model below
  Enterprise, two recommended plans, a trial on a plan not bought online —
  is refused when read.
- What a plan costs: the list price monthly; 20% off the first 12 months
  on monthly billing (the launch offer); 30% off billed yearly — never
  both; whole cents, the same on the page and at checkout. Not eligible, or
  the offer closed: the list price. Growth's trial: the first charge 14 days
  after, of what the period costs; not eligible, charged the day bought.
- GET /pricing, open to anyone, says exactly that; the booking address only
  when configured, the contact form always. A visitor's clicks are recorded
  — what, on which plan, never who — refused when they are not the page's,
  quietly dropped past the limit.
"""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

from leka.api import pricing as pricing_api
from leka.billing import Catalogue, catalogue, load, quote
from leka.billing.catalogue import CATALOGUE_FILE
from leka.core.config import settings
from leka.db import session_factory, system_scope

TODAY = date(2026, 10, 17)

# The module itself: `leka.governance.plans` is also the name of a function
# the package exports.
governance_plans = importlib.import_module("leka.governance.plans")


def _raw() -> dict[str, Any]:
    said: dict[str, Any] = yaml.safe_load(CATALOGUE_FILE.read_text(encoding="utf-8"))
    return said


# ── the catalogue ───────────────────────────────────────────────────────────


def test_the_catalogue_lekas_ships_is_whole() -> None:
    offer = catalogue()
    assert [p.key for p in offer.plans] == ["free", "starter", "growth", "business", "enterprise"]
    assert [p.monthly_price for p in offer.plans] == [0, 5900, 17900, 59900, None]
    assert [p.key for p in offer.plans if p.recommended] == ["growth"]
    assert [p.key for p in offer.plans if p.trial_days] == ["growth"]
    assert offer.plan("growth").trial_days == 14
    # LEKA's own capabilities are every plan's; each plan includes some of
    # the registry's agents, every plan above it too (Karim, 2026-10-15).
    sold_ = offer.add_ons
    assert {"application-architecture", "test-analysis"} <= set(sold_.agents)
    assert sold_.included_in("free") == frozenset()
    assert sold_.included_in("starter") == {
        "code-review",
        "test-analysis",
        "documentation-assistant",
    }
    assert len(sold_.included_in("growth")) == 8
    # Enterprise, by contract, every one; Business, every one of Karim's
    # matrix — Frontend Craft's, built after it, options below Enterprise
    # until he says (LEKA-461).
    assert sold_.included_in("enterprise") == set(sold_.agents)
    frontend = {"ui-quality-review", "accessibility-audit", "design-review", "motion-review"}
    assert sold_.included_in("business") == set(sold_.agents) - frontend
    assert "core_agents" not in _raw()
    assert [p.key for p in offer.plans if p.own_llm] == ["enterprise"]
    assert all(p.managed_llm for p in offer.plans)
    enterprise = offer.plan("enterprise")
    assert (enterprise.self_service, enterprise.ai_credits_per_month.contractual) == (False, True)
    allowances = {p.key: p.ai_credits_per_month for p in offer.plans if p.key != "enterprise"}
    assert all(c.provisional and not c.contractual for c in allowances.values())
    assert (offer.annual_discount_percent, offer.launch_offer.percent) == (30, 20)
    assert (offer.launch_offer.months, offer.launch_offer.intervals) == (12, ("month",))
    # On sale since 2026-10-14, from Starter: each agent at its tier's price
    # (to validate), the bundles cheaper than their agents alone — never at
    # a loss.
    sold = offer.add_ons
    assert (sold.available, sold.provisional, sold.minimum_plan) == (True, True, "starter")
    assert sold.tiers == {"standard": 900, "specialized": 1500, "expert": 2500}
    assert sold.prices["application-architecture"] == 2500
    assert sold.prices["code-review"] == 900
    # The reference's bundles, at its prices (LEKA-454), sold once every
    # agent they name is built: Frontend Craft only (LEKA-461). Their saving
    # computed, shown only when it can be.
    assert {b.key: b.monthly_price for b in sold.bundles} == {
        "engineering": 5900,
        "ship-safe": 7900,
        "incident-response": 8900,
        "security-reliability": 6900,
        "frontend-craft": 2900,
    }
    assert [b.key for b in sold.bundles if b.sellable] == ["frontend-craft"]
    assert {b.key: b.savings_percent for b in sold.bundles} == {
        "engineering": 35,
        "ship-safe": None,
        "incident-response": None,
        "security-reliability": None,
        "frontend-craft": 40,
    }
    # Each plan's quotas, to validate; Enterprise's by contract.
    assert [p.quotas.sources for p in offer.plans] == [3, 5, 15, 30, None]
    assert offer.plan("enterprise").quotas.contractual is True
    # The AI capacity is the plan's: nothing sells it apart.
    assert _raw()["capacity"] == {"automatic_overage": False}


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda c: c["launch_offer"].update(intervals=["month", "year"]), "never stacks"),
        (lambda c: c["plans"][2].update(own_llm=True), "Enterprise only"),
        (lambda c: c["plans"][1].update(recommended=True), "one recommended"),
        (lambda c: c["plans"].pop(), "the five plans"),
        (lambda c: c["capacity"].update(automatic_overage=True), "automatic_overage"),
        (lambda c: c["plans"][4].update(self_service=True), "has a price"),
        (lambda c: c["plans"][0].update(trial_days=14), "a trial needs"),
        (lambda c: c["capacity"].update(packs=[]), "Extra inputs"),
        (
            lambda c: c["add_ons"]["bundles"][0].update(monthly_price=9900),
            "no cheaper than its agents alone",
        ),
        (lambda c: c["add_ons"]["bundles"][0]["members"].append("ghost"), "not in the reference"),
        (lambda c: c["add_ons"].update(included={"growth": ["ghost"]}), "not in the registry"),
        (lambda c: c["add_ons"]["agents"]["code-review"].update(reference="ghost"), "ghost"),
    ],
)
def test_a_catalogue_that_breaks_a_rule_is_refused(tmp_path: Path, change: Any, said: str) -> None:
    raw = _raw()
    change(raw)
    broken = tmp_path / "catalogue.yaml"
    broken.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError, match=said):
        load(broken)


# ── what a plan costs ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("plan", "launch_monthly", "annual_monthly", "annual_charged"),
    [
        ("starter", 4720, 4130, 49560),
        ("growth", 14320, 12530, 150360),
        ("business", 47920, 41930, 503160),
    ],
)
def test_the_launch_offer_or_the_annual_discount_never_both(
    plan: str, launch_monthly: int, annual_monthly: int, annual_charged: int
) -> None:
    offer = catalogue()
    chosen = offer.plan(plan)
    monthly = quote(chosen, "month", offer, today=TODAY)
    assert (monthly.discount, monthly.percent, monthly.monthly, monthly.charged) == (
        "launch",
        20,
        launch_monthly,
        launch_monthly,
    )
    assert (monthly.for_months, monthly.then_monthly) == (12, chosen.monthly_price)
    yearly = quote(chosen, "year", offer, today=TODAY)
    assert (yearly.discount, yearly.percent, yearly.monthly, yearly.charged) == (
        "annual",
        30,
        annual_monthly,
        annual_charged,
    )
    # Never stacked: a year is 30% off, never 20% then 30%.
    assert yearly.for_months is None
    # Not eligible: the list price.
    plain = quote(chosen, "month", offer, today=TODAY, launch=False)
    assert (plain.discount, plain.monthly) == (None, chosen.monthly_price)


def test_growth_s_trial_says_when_and_what_is_first_charged() -> None:
    offer = catalogue()
    growth = offer.plan("growth")
    monthly = quote(growth, "month", offer, today=TODAY)
    # 14 days free, then the launch price — the 20% for 12 months.
    assert (monthly.trial_days, monthly.first_charge_on) == (14, date(2026, 10, 31))
    assert (monthly.charged, monthly.then_monthly) == (14320, 17900)
    yearly = quote(growth, "year", offer, today=TODAY)
    assert (yearly.first_charge_on, yearly.charged) == (date(2026, 10, 31), 150360)
    # Had once already: charged the day it is bought.
    again = quote(growth, "month", offer, today=TODAY, trial=False)
    assert (again.trial_days, again.first_charge_on) == (None, None)
    # The other plans have none.
    assert quote(offer.plan("starter"), "month", offer, today=TODAY).trial_days is None


def test_the_offer_closed_or_a_plan_without_it_pays_the_list_price() -> None:
    offer = catalogue()
    closed = Catalogue.model_validate(
        {**_raw(), "launch_offer": {**_raw()["launch_offer"], "ends_on": "2026-10-01"}}
    )
    assert quote(closed.plan("growth"), "month", closed, today=TODAY).discount is None
    free = quote(offer.plan("free"), "month", offer, today=TODAY)
    assert (free.discount, free.charged) == (None, 0)
    with pytest.raises(ValueError, match="not sold yearly"):
        quote(offer.plan("free"), "year", offer, today=TODAY)
    with pytest.raises(ValueError, match="per contract"):
        quote(offer.plan("enterprise"), "month", offer, today=TODAY)


# ── over HTTP ───────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_anyone_reads_the_pricing_as_checkout_charges_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pricing_api, "settings", settings.model_copy(update={"sales_booking_url": None})
    )
    response = await client.get("/api/v1/pricing")
    assert response.status_code == 200
    said = response.json()
    growth = next(p for p in said["plans"] if p["key"] == "growth")
    assert growth["recommended"] is True
    assert [(q["interval"], q["discount"], q["charged"]) for q in growth["quotes"]] == [
        ("month", "launch", 14320),
        ("year", "annual", 150360),
    ]
    enterprise = next(p for p in said["plans"] if p["key"] == "enterprise")
    assert (enterprise["quotes"], enterprise["own_llm"], enterprise["self_service"]) == (
        [],
        True,
        False,
    )
    assert said["launch_offer"]["stacks_with_annual"] is False
    assert said["add_ons_available"] is True
    assert said["automatic_overage"] is False
    # Nothing that sells AI capacity, nor an agent in a plan.
    assert not {"capacity_any_time", "capacity_packs_available", "core_agents"} & set(said)
    assert [(p["key"], p["trial_days"]) for p in said["plans"] if p["trial_days"]] == [
        ("growth", 14)
    ]
    assert growth["quotes"][0]["first_charge_on"] is not None
    # No booking page configured: none guessed; the contact form always.
    assert said["booking"]["url"] is None
    assert said["booking"]["contact_url"].startswith("https://")

    booking = "https://calendly.com/example/leka"
    monkeypatch.setattr(
        pricing_api, "settings", settings.model_copy(update={"sales_booking_url": booking})
    )
    booked = (await client.get("/api/v1/pricing")).json()
    assert booked["booking"]["url"] == "https://calendly.com/example/leka"


async def test_the_credits_shown_are_the_ones_metering_grants(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One figure, metering's (LEKA-430): the page cannot promise other than
    what a workspace gets — and follows LEKA_PLAN_CREDITS when it changes."""
    said = (await client.get("/api/v1/pricing")).json()
    granted = {p["key"]: p["ai_credits_per_month"] for p in said["plans"]}
    assert granted == {
        "free": 200,
        "starter": 2000,
        "growth": 10000,
        "business": 40000,
        "enterprise": None,  # per contract
    }
    assert granted["growth"] == governance_plans.plan_credits("growth")

    changed = {**settings.plan_credits, "growth": 12000}
    monkeypatch.setattr(
        governance_plans, "settings", settings.model_copy(update={"plan_credits": changed})
    )
    again = (await client.get("/api/v1/pricing")).json()
    assert next(p for p in again["plans"] if p["key"] == "growth")["ai_credits_per_month"] == 12000


@pytest.mark.integration
async def test_a_visitors_clicks_are_counted_never_who(client: AsyncClient) -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM site_events"))
            await session.commit()
    for body in (
        {"event": "page_viewed", "language": "fr"},
        {"event": "interval_selected", "interval": "year"},
        {"event": "plan_selected", "plan": "growth", "interval": "month"},
        {"event": "enterprise_booking_clicked", "plan": "enterprise"},
    ):
        answered = await client.post("/api/v1/pricing/events", json=body)
        assert answered.status_code == 204, answered.text
    wrong = await client.post("/api/v1/pricing/events", json={"event": "bought", "email": "x"})
    assert wrong.status_code == 422
    with system_scope():
        async with session_factory() as session:
            rows = (
                await session.execute(
                    text("SELECT event, plan, interval FROM site_events ORDER BY at, event")
                )
            ).all()
            columns = (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'site_events'"
                    )
                )
            ).scalars()
            names = set(columns)
    assert {tuple(r) for r in rows} == {
        ("page_viewed", None, None),
        ("interval_selected", None, "year"),
        ("plan_selected", "growth", "month"),
        ("enterprise_booking_clicked", "enterprise", None),
    }
    # Who and from where: never kept.
    assert not names & {"user_id", "workspace_id", "ip", "address", "email"}
