"""LEKA CORE's commercial catalogue and what each plan costs (LEKA-431) —
pure, and over HTTP.

What these protect:
- The catalogue LEKA ships is whole and coherent: five plans in order,
  Growth the one recommended; Architect and QA included in every plan;
  connecting one's own model only on Enterprise, priced per contract and
  never self-service; AI credits a number marked provisional (Enterprise:
  by contract); specialist add-ons and capacity packs not on sale until
  available; never an automatic overage charge. A catalogue that breaks a
  rule — the launch offer on yearly billing, own model below Enterprise,
  two recommended plans — is refused when read.
- What a plan costs: the list price monthly; 30% off the first 12 months
  on monthly billing (the launch offer); 20% off billed yearly — never
  both; whole cents, the same on the page and at checkout. Not eligible, or
  the offer closed: the list price.
- GET /pricing, open to anyone, says exactly that; the booking address only
  when configured, the contact form always. A visitor's clicks are recorded
  — what, on which plan, never who — refused when they are not the page's,
  quietly dropped past the limit.
"""

from __future__ import annotations

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


def _raw() -> dict[str, Any]:
    said: dict[str, Any] = yaml.safe_load(CATALOGUE_FILE.read_text(encoding="utf-8"))
    return said


# ── the catalogue ───────────────────────────────────────────────────────────


def test_the_catalogue_lekas_ships_is_whole() -> None:
    offer = catalogue()
    assert [p.key for p in offer.plans] == ["free", "starter", "growth", "business", "enterprise"]
    assert [p.monthly_price for p in offer.plans] == [0, 5900, 17900, 59900, None]
    assert [p.key for p in offer.plans if p.recommended] == ["growth"]
    assert [a.key for a in offer.core_agents] == ["application-architecture", "test-analysis"]
    assert [p.key for p in offer.plans if p.own_llm] == ["enterprise"]
    assert all(p.managed_llm for p in offer.plans)
    enterprise = offer.plan("enterprise")
    assert (enterprise.self_service, enterprise.ai_credits_per_month.contractual) == (False, True)
    allowances = {p.key: p.ai_credits_per_month for p in offer.plans if p.key != "enterprise"}
    assert {k: c.value for k, c in allowances.items()} == {
        "free": 100,
        "starter": 500,
        "growth": 2000,
        "business": 8000,
    }
    assert all(c.provisional for c in allowances.values())
    assert (offer.annual_discount_percent, offer.launch_offer.percent) == (20, 30)
    assert (offer.launch_offer.months, offer.launch_offer.intervals) == (12, ("month",))
    assert offer.add_ons.available is False and offer.capacity.packs == ()
    assert offer.capacity.purchase_any_time and offer.capacity.automatic_overage is False


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda c: c["launch_offer"].update(intervals=["month", "year"]), "never stacks"),
        (lambda c: c["plans"][2].update(own_llm=True), "Enterprise only"),
        (lambda c: c["plans"][1].update(recommended=True), "one recommended"),
        (lambda c: c["plans"].pop(), "the five plans"),
        (lambda c: c["capacity"].update(automatic_overage=True), "automatic_overage"),
        (lambda c: c["plans"][4].update(self_service=True), "has a price"),
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
        ("starter", 4130, 4720, 56640),
        ("growth", 12530, 14320, 171840),
        ("business", 41930, 47920, 575040),
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
        30,
        launch_monthly,
        launch_monthly,
    )
    assert (monthly.for_months, monthly.then_monthly) == (12, chosen.monthly_price)
    yearly = quote(chosen, "year", offer, today=TODAY)
    assert (yearly.discount, yearly.percent, yearly.monthly, yearly.charged) == (
        "annual",
        20,
        annual_monthly,
        annual_charged,
    )
    # Never stacked: a year is 20% off, never 30% then 20%.
    assert yearly.for_months is None
    # Not eligible: the list price.
    plain = quote(chosen, "month", offer, today=TODAY, launch=False)
    assert (plain.discount, plain.monthly) == (None, chosen.monthly_price)


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
        ("month", "launch", 12530),
        ("year", "annual", 171840),
    ]
    enterprise = next(p for p in said["plans"] if p["key"] == "enterprise")
    assert (enterprise["quotes"], enterprise["own_llm"], enterprise["self_service"]) == (
        [],
        True,
        False,
    )
    assert said["launch_offer"]["stacks_with_annual"] is False
    assert (said["add_ons_available"], said["capacity_packs_available"]) == (False, False)
    assert said["automatic_overage"] is False
    # No booking page configured: none guessed; the contact form always.
    assert said["booking"]["url"] is None
    assert said["booking"]["contact_url"].startswith("https://")

    booking = "https://calendly.com/example/leka"
    monkeypatch.setattr(
        pricing_api, "settings", settings.model_copy(update={"sales_booking_url": booking})
    )
    booked = (await client.get("/api/v1/pricing")).json()
    assert booked["booking"]["url"] == "https://calendly.com/example/leka"


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
