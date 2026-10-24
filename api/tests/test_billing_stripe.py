"""Paying for LEKA CORE with Stripe (LEKA-431, LEKA-446) — on a Stripe whose
API is faked, its webhooks signed as Stripe signs them.

What these protect:
- A webhook is believed only when its signature holds: another secret, a
  changed body, an old timestamp — refused. Stripe's form encoding.
- The catalogue in Stripe: each plan a product, each price found by its
  lookup key, the launch offer a coupon — made once; run again, nothing.
- Checkout: only who may change the workspace pays; nothing without Stripe
  configured; the price the page shows — found by its key — the launch
  coupon on the first monthly subscription only, never on a year, never
  twice; a workspace already subscribed goes to the portal. Growth's trial:
  14 days, a card required, ended without one; said with its first charge
  before paying; once a workspace — never on a second subscription.
- The plan comes only from a verified event: checkout completed puts the
  workspace on its plan, once — the same event delivered again changes
  nothing; past_due keeps it while Stripe retries; deleted, back to Free;
  an older event delivered late never undoes a newer one.
- The trial: trialing is Growth; converted at its end, Growth still;
  cancelled before, back to Free. A renewal that fails holds the plan while
  Stripe retries, then, unpaid, back to Free.
- No AI capacity is sold: no route for it, a one-time payment credits
  nothing.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select

from leka.api import subscriptions as subscriptions_api
from leka.billing import Stripe, catalogue, sync
from leka.billing import subscriptions as billing
from leka.billing.stripe import SignatureError, form, sign, verify
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from leka.governance import CreditPack, WorkspacePlan, plan_of
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

SECRET = "whsec_test_secret"
API = "/api/v1/billing"


# ── pure ────────────────────────────────────────────────────────────────────


def test_a_webhook_is_believed_only_when_signed() -> None:
    body = json.dumps({"id": "evt_1", "type": "invoice.paid"}).encode()
    now = 1_800_000_000
    assert verify(body, sign(body, SECRET, at=now), SECRET, now=now + 10)["id"] == "evt_1"
    for header, payload, at in (
        (sign(body, "whsec_other", at=now), body, now),
        (sign(body, SECRET, at=now), body.replace(b"evt_1", b"evt_2"), now),
        (sign(body, SECRET, at=now), body, now + 3600),
        ("v1=abc", body, now),
    ):
        with pytest.raises(SignatureError):
            verify(payload, header, SECRET, now=at)


def test_stripes_form_encoding() -> None:
    said = form(
        {
            "mode": "subscription",
            "line_items": [{"price": "price_1", "quantity": 1}],
            "discounts": None,
            "metadata": {"plan": "growth", "launch": True},
        }
    )
    assert said == [
        ("mode", "subscription"),
        ("line_items[0][price]", "price_1"),
        ("line_items[0][quantity]", "1"),
        ("metadata[plan]", "growth"),
        ("metadata[launch]", "true"),
    ]


# ── a fake Stripe ───────────────────────────────────────────────────────────


class FakeStripe:
    """Stripe's API as LEKA uses it — what it was asked kept."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, dict[str, str]]] = []
        self.products: set[str] = set()
        self.prices: dict[str, str] = {}
        self.coupons: set[str] = set()
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.portals: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = dict(parse_qsl(request.content.decode())) if request.content else {}
        self.asked.append((request.method, path, body))
        if request.method == "GET" and path.startswith("/v1/products/"):
            found = path.removeprefix("/v1/products/") in self.products
            return httpx.Response(200 if found else 404, json={} if found else {"error": {}})
        if request.method == "POST" and path == "/v1/products":
            self.products.add(body["id"])
            return httpx.Response(200, json={"id": body["id"]})
        if request.method == "GET" and path == "/v1/prices":
            key = request.url.params.get("lookup_keys[]")
            listed = [{"id": self.prices[key]}] if key in self.prices else []
            return httpx.Response(200, json={"data": listed})
        if request.method == "POST" and path == "/v1/prices":
            self.prices[body["lookup_key"]] = f"price_{len(self.prices) + 1}"
            return httpx.Response(200, json={"id": self.prices[body["lookup_key"]]})
        if request.method == "GET" and path.startswith("/v1/coupons/"):
            found = path.removeprefix("/v1/coupons/") in self.coupons
            return httpx.Response(200 if found else 404, json={} if found else {"error": {}})
        if request.method == "POST" and path == "/v1/coupons":
            self.coupons.add(body["id"])
            return httpx.Response(200, json={"id": body["id"]})
        if request.method == "POST" and path == "/v1/customers":
            return httpx.Response(200, json={"id": "cus_1"})
        if request.method == "POST" and path == "/v1/checkout/sessions":
            return httpx.Response(
                200, json={"id": "cs_1", "url": "https://checkout.stripe.test/cs_1"}
            )
        if request.method == "GET" and path == "/v1/billing_portal/configurations":
            return httpx.Response(200, json={"data": self.portals})
        if request.method == "POST" and path == "/v1/billing_portal/configurations":
            self.portals.append(
                {
                    "id": "bpc_1",
                    "metadata": {"leka": body["metadata[leka]"]},
                    "features": {"subscription_update": {"products": _products(body)}},
                }
            )
            return httpx.Response(200, json={"id": "bpc_1"})
        if request.method == "POST" and path.startswith("/v1/billing_portal/configurations/"):
            # Its plans' prices given again, every price sold now (2026-10-24).
            portal = next(p for p in self.portals if p["id"] == path.rsplit("/", 1)[-1])
            portal["features"] = {"subscription_update": {"products": _products(body)}}
            return httpx.Response(200, json={"id": portal["id"]})
        if request.method == "POST" and path == "/v1/billing_portal/sessions":
            return httpx.Response(200, json={"url": "https://billing.stripe.test/p_1"})
        if request.method == "GET" and path.startswith("/v1/subscriptions/"):
            return httpx.Response(
                200, json=self.subscriptions[path.removeprefix("/v1/subscriptions/")]
            )
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})

    def posted(self, path: str) -> list[dict[str, str]]:
        return [body for method, p, body in self.asked if method == "POST" and p == path]

    def client(self) -> Stripe:
        return Stripe(
            "sk_test_fake", base_url="https://stripe.test", transport=httpx.MockTransport(self)
        )


def _products(body: dict[str, str]) -> list[dict[str, Any]]:
    """The products and prices a portal configuration lists, read back from
    Stripe's form encoding."""
    found: dict[str, dict[str, Any]] = {}
    for name, value in body.items():
        parts = re.findall(r"\[([^\]]*)\]", name)
        if "products" not in parts:
            continue
        at = parts[parts.index("products") + 1]
        product = found.setdefault(at, {"product": None, "prices": []})
        if parts[-1] == "product":
            product["product"] = value
        elif "prices" in parts:
            product["prices"].append(value)
    return list(found.values())


def subscription(
    plan: str, status: str, *, sub: str = "sub_1", interval: str = "month"
) -> dict[str, Any]:
    return {
        "id": sub,
        "object": "subscription",
        "customer": "cus_1",
        "status": status,
        "current_period_end": 1_900_000_000,
        "cancel_at_period_end": False,
        "metadata": {"leka_plan": plan},
        "items": {
            "data": [
                {
                    "id": "si_1",
                    "price": {"metadata": {"leka_plan": plan}, "recurring": {"interval": interval}},
                }
            ]
        },
    }


@pytest.fixture
def stripe(monkeypatch: pytest.MonkeyPatch) -> FakeStripe:
    fake = FakeStripe()
    configured = settings.model_copy(
        update={
            "stripe_secret_key": SecretStr("sk_test_fake"),
            "stripe_webhook_secret": SecretStr(SECRET),
            "web_url": "https://leka.test",
        }
    )
    monkeypatch.setattr(billing, "settings", configured)
    monkeypatch.setattr(subscriptions_api, "stripe", fake.client)
    return fake


async def _synced(fake: FakeStripe) -> None:
    await sync(fake.client(), catalogue(), today=datetime.now(UTC).date())


async def _deliver(client: AsyncClient, event: dict[str, Any]) -> httpx.Response:
    body = json.dumps(event).encode()
    return await client.post(
        f"{API}/stripe/webhook",
        content=body,
        headers={
            "Stripe-Signature": sign(body, SECRET, at=int(time.time())),
            "Content-Type": "application/json",
        },
    )


def _event(
    kind: str, data: dict[str, Any], *, created: int, event: str | None = None
) -> dict[str, Any]:
    return {
        "id": event or f"evt_{uuid.uuid4().hex[:10]}",
        "type": kind,
        "created": created,
        "data": {"object": data},
    }


async def _plan(workspace: uuid.UUID) -> str:
    with workspace_scope(workspace):
        async with session_factory() as session:
            return (await plan_of(session, workspace)).name


async def _count(workspace: uuid.UUID, table: type[Any]) -> int:
    with workspace_scope(workspace):
        async with session_factory() as session:
            return int(
                await session.scalar(
                    select(func.count()).select_from(table).where(table.workspace_id == workspace)
                )
                or 0
            )


# ── the catalogue in Stripe ─────────────────────────────────────────────────


async def test_the_catalogue_is_made_in_stripe_once() -> None:
    fake = FakeStripe()
    done = await sync(fake.client(), catalogue(), today=date(2026, 10, 17))
    assert {k for k in done.prices if k.startswith("leka_core_")} == {
        "leka_core_starter_month_5900",
        "leka_core_starter_year_49560",
        "leka_core_growth_month_17900",
        "leka_core_growth_year_150360",
        "leka_core_business_month_59900",
        "leka_core_business_year_503160",
    }
    assert {p for p in fake.products if p.startswith("leka_core_")} == {
        "leka_core_starter",
        "leka_core_growth",
        "leka_core_business",
    }
    # Each agent and bundle a product and a monthly price (LEKA-461), found
    # by a key that says its amount.
    assert "leka_addon_agent_security-review" in fake.products
    assert "leka_addon_agent_security-review_month_2500" in done.prices
    assert "leka_addon_bundle_engineering_month_5900" in done.prices
    agent = next(
        p for p in fake.posted("/v1/prices") if p["lookup_key"].startswith("leka_addon_agent_")
    )
    assert (agent["recurring[interval]"], agent["tax_behavior"], agent["currency"]) == (
        "month",
        "exclusive",
        "eur",
    )
    assert fake.coupons == {"leka_launch_20_12m"}
    [coupon] = fake.posted("/v1/coupons")
    assert (coupon["percent_off"], coupon["duration"], coupon["duration_in_months"]) == (
        "20",
        "repeating",
        "12",
    )
    yearly = next(p for p in fake.posted("/v1/prices") if p["lookup_key"].endswith("_year_150360"))
    assert (yearly["unit_amount"], yearly["recurring[interval]"], yearly["currency"]) == (
        "150360",
        "year",
        "eur",
    )
    # Its portal: cancellation at the period's end, a change prorated, each
    # plan's two prices.
    [portal] = fake.posted("/v1/billing_portal/configurations")
    assert portal["features[subscription_cancel][mode]"] == "at_period_end"
    assert portal["features[subscription_update][proration_behavior]"] == "create_prorations"
    growth = [k for k, v in portal.items() if v == "leka_core_growth"]
    assert growth and done.portal == "bpc_1"
    again = await sync(fake.client(), catalogue(), today=date(2026, 10, 17))
    assert again.created == [] and again.prices == done.prices


# ── checkout ────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_checkout_charges_what_the_page_shows_the_launch_offer_once(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    await _synced(stripe)
    _as(identity, acme, "member")
    asked = {"plan": "growth", "interval": "month"}
    assert (await client.post(f"{API}/checkout", json=asked)).status_code == 403
    _as(identity, acme, "admin")
    # Free and Enterprise are not bought here.
    for plan in ("free", "enterprise"):
        refused = await client.post(f"{API}/checkout", json={"plan": plan, "interval": "month"})
        assert refused.status_code == 422

    opened = await client.post(f"{API}/checkout", json=asked)
    assert opened.status_code == 200, opened.text
    said = opened.json()
    assert said["url"] == "https://checkout.stripe.test/cs_1"
    assert (said["quote"]["discount"], said["quote"]["charged"]) == ("launch", 14320)
    [session] = stripe.posted("/v1/checkout/sessions")
    assert session["mode"] == "subscription"
    assert session["line_items[0][price]"] == stripe.prices["leka_core_growth_month_17900"]
    assert session["discounts[0][coupon]"] == "leka_launch_20_12m"
    assert session["client_reference_id"] == str(acme["acme"])
    assert session["success_url"] == "https://leka.test/billing?checkout=success"
    # A year: the annual discount, never the coupon as well.
    yearly = await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "year"})
    assert yearly.json()["quote"]["discount"] == "annual"
    session = stripe.posted("/v1/checkout/sessions")[-1]
    assert session["line_items[0][price]"] == stripe.prices["leka_core_growth_year_150360"]
    assert "discounts[0][coupon]" not in session
    # One Stripe customer for the workspace.
    assert len(stripe.posted("/v1/customers")) == 1


@pytest.mark.integration
async def test_a_yearly_plan_the_catalogue_changed_since_the_sync_is_bought_all_the_same(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    """2026-10-24: the annual discount went from 20 % to 30 % after the last
    sync — no yearly price in Stripe, none in the portal: « impossible
    d'acheter l'annuel ». The price is made at checkout, and the portal given
    it before a subscriber's change to it."""
    await _synced(stripe)
    yearly = next(k for k in stripe.prices if k.startswith("leka_core_growth_year_"))
    stripe.prices.pop(yearly)
    for portal in stripe.portals:
        for product in portal["features"]["subscription_update"]["products"]:
            product["prices"] = [p for p in product["prices"] if p.startswith("price_")][:1]
    _as(identity, acme, "admin")
    workspace = acme["acme"]

    bought = await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "year"})
    assert bought.status_code == 200, bought.text
    assert yearly in stripe.prices
    [opened] = stripe.posted("/v1/checkout/sessions")
    assert opened["line_items[0][price]"] == stripe.prices[yearly]

    # Subscribed monthly, then yearly: the portal lists the yearly price.
    stripe.subscriptions["sub_1"] = subscription("growth", "active")
    await _deliver(
        client,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_1",
                "mode": "subscription",
                "subscription": "sub_1",
                "customer": "cus_1",
                "client_reference_id": str(workspace),
            },
            created=1_800_000_100,
        ),
    )
    changed = await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "year"})
    assert changed.status_code == 200, changed.text
    listed = [
        price
        for product in stripe.portals[0]["features"]["subscription_update"]["products"]
        for price in product["prices"]
    ]
    assert stripe.prices[yearly] in listed
    [session] = stripe.posted("/v1/billing_portal/sessions")
    assert (
        session["flow_data[subscription_update_confirm][items][0][price]"] == stripe.prices[yearly]
    )


async def test_subscribed_the_chosen_plan_confirmed_in_stripe_never_a_second_subscription(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    """LEKA-490: once subscribed, « Choisir Business » opens Stripe on the
    change to Business's exact price — prorated there — never Checkout, never
    the portal's front page; the same plan refused; back to Free, its end."""
    await _synced(stripe)
    _as(identity, acme, "admin")
    workspace = acme["acme"]
    stripe.subscriptions["sub_1"] = subscription("growth", "active")
    await _deliver(
        client,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_1",
                "mode": "subscription",
                "subscription": "sub_1",
                "customer": "cus_1",
                "client_reference_id": str(workspace),
            },
            created=1_800_000_100,
        ),
    )
    assert await _plan(workspace) == "growth"

    changed = await client.post(f"{API}/checkout", json={"plan": "business", "interval": "month"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["url"] == "https://billing.stripe.test/p_1"
    assert changed.json()["quote"]["discount"] is None
    [opened] = stripe.posted("/v1/billing_portal/sessions")
    assert opened["flow_data[type]"] == "subscription_update_confirm"
    assert opened["flow_data[subscription_update_confirm][subscription]"] == "sub_1"
    assert opened["flow_data[subscription_update_confirm][items][0][id]"] == "si_1"
    business = next(
        v for k, v in stripe.prices.items() if k.startswith("leka_core_business_month_")
    )
    assert opened["flow_data[subscription_update_confirm][items][0][price]"] == business
    assert (
        opened["flow_data[after_completion][redirect][return_url]"]
        == "https://leka.test/billing?changed=success"
    )
    # Never a second subscription; the plan changes only with Stripe's event.
    assert stripe.posted("/v1/checkout/sessions") == []
    assert await _plan(workspace) == "growth"

    # Growth yearly is a change too; Growth monthly is what it has.
    yearly = await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "year"})
    assert yearly.status_code == 200
    same = await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "month"})
    assert same.status_code == 409
    assert same.json()["error"]["details"][0]["message"] == "same_plan"

    ending = await client.post(f"{API}/portal", params={"flow": "cancel"})
    assert ending.status_code == 200
    cancel = stripe.posted("/v1/billing_portal/sessions")[-1]
    assert cancel["flow_data[type]"] == "subscription_cancel"
    assert cancel["flow_data[subscription_cancel][subscription]"] == "sub_1"


@pytest.mark.integration
async def test_without_stripe_nothing_can_be_bought(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    refused = await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "month"})
    assert refused.status_code == 503
    said = (await client.get(f"{API}/subscription")).json()
    assert (said["available"], said["plan"], said["launch_offer_available"]) == (
        False,
        "free",
        True,
    )


# ── what Stripe says ────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_the_plan_comes_from_verified_events_once_never_undone_by_an_older_one(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    workspace = acme["acme"]
    await _synced(stripe)
    _as(identity, acme, "admin")
    assert (
        await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "month"})
    ).status_code == 200

    # Not signed by Stripe: refused, nothing changes.
    forged = await client.post(
        f"{API}/stripe/webhook",
        content=b'{"id": "evt_x", "type": "checkout.session.completed"}',
        headers={"Stripe-Signature": "t=1,v1=nope"},
    )
    assert forged.status_code == 400
    assert await _plan(workspace) == "free"

    stripe.subscriptions["sub_1"] = subscription("growth", "active")
    completed = _event(
        "checkout.session.completed",
        {
            "id": "cs_1",
            "mode": "subscription",
            "subscription": "sub_1",
            "customer": "cus_1",
            "client_reference_id": str(workspace),
        },
        created=1_800_000_100,
        event="evt_completed",
    )
    answered = await _deliver(client, completed)
    assert answered.status_code == 200 and answered.json() == {"received": "plan:growth"}
    assert await _plan(workspace) == "growth"
    plans_before = await _count(workspace, WorkspacePlan)
    # Delivered again: nothing more.
    assert (await _deliver(client, completed)).json() == {"received": "duplicate"}
    assert await _count(workspace, WorkspacePlan) == plans_before

    said = (await client.get(f"{API}/subscription")).json()
    assert (said["plan"], said["interval"], said["status"], said["launch_offer_available"]) == (
        "growth",
        "month",
        "active",
        False,
    )
    # Subscribed: another plan is a change confirmed in Stripe, never a
    # second subscription (LEKA-490).
    sessions = len(stripe.posted("/v1/checkout/sessions"))
    again = await client.post(f"{API}/checkout", json={"plan": "business", "interval": "month"})
    assert again.status_code == 200
    assert len(stripe.posted("/v1/checkout/sessions")) == sessions
    portal = await client.post(f"{API}/portal")
    assert portal.json() == {"url": "https://billing.stripe.test/p_1"}

    # A failed payment: Stripe retries, the plan holds.
    past_due = _event(
        "customer.subscription.updated", subscription("growth", "past_due"), created=1_800_000_200
    )
    assert (await _deliver(client, past_due)).json() == {"received": "plan:growth"}
    failed = _event(
        "invoice.payment_failed", {"customer": "cus_1", "id": "in_1"}, created=1_800_000_210
    )
    assert (await _deliver(client, failed)).json() == {"received": "payment_failed"}
    assert await _plan(workspace) == "growth"
    # Deleted: back to Free.
    deleted = _event(
        "customer.subscription.deleted", subscription("growth", "canceled"), created=1_800_000_300
    )
    assert (await _deliver(client, deleted)).json() == {"received": "plan:free"}
    assert await _plan(workspace) == "free"
    # An older update, delivered late, never undoes it.
    late = _event(
        "customer.subscription.updated", subscription("growth", "active"), created=1_800_000_250
    )
    assert (await _deliver(client, late)).json() == {"received": "stale"}
    assert await _plan(workspace) == "free"
    # Subscribed once: the launch offer is gone for good.
    reopened = await client.post(f"{API}/checkout", json={"plan": "starter", "interval": "month"})
    assert reopened.json()["quote"]["discount"] is None
    assert "discounts[0][coupon]" not in stripe.posted("/v1/checkout/sessions")[-1]


@pytest.mark.integration
async def test_a_declined_card_spends_no_offer_and_its_expiry_never_undoes_the_paid_plan(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    # As seen on Stripe's test mode (2026-10-15): card 4000…0002, then 4242….
    workspace = acme["acme"]
    await _synced(stripe)
    _as(identity, acme, "admin")
    declined = subscription("starter", "incomplete", sub="sub_declined")
    created = _event("customer.subscription.created", declined, created=1_800_000_100)
    assert (await _deliver(client, created)).json() == {"received": "ignored"}
    assert await _plan(workspace) == "free"
    said = (await client.get(f"{API}/subscription")).json()
    assert (said["launch_offer_available"], said["trial_available"]) == (True, True)
    retried = await client.post(f"{API}/checkout", json={"plan": "starter", "interval": "month"})
    assert retried.json()["quote"]["discount"] == "launch"

    stripe.subscriptions["sub_paid"] = subscription("starter", "active", sub="sub_paid")
    completed = _event(
        "checkout.session.completed",
        {
            "id": "cs_2",
            "mode": "subscription",
            "subscription": "sub_paid",
            "customer": "cus_1",
            "client_reference_id": str(workspace),
        },
        created=1_800_000_200,
    )
    assert (await _deliver(client, completed)).json() == {"received": "plan:starter"}
    # A day later Stripe lets the declined one expire: the paid plan holds.
    expired = subscription("starter", "incomplete_expired", sub="sub_declined")
    late = _event("customer.subscription.updated", expired, created=1_800_086_400)
    assert (await _deliver(client, late)).json() == {"received": "ignored"}
    assert await _plan(workspace) == "starter"
    said = (await client.get(f"{API}/subscription")).json()
    assert (said["status"], said["launch_offer_available"]) == ("active", False)


# ── the trial ───────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_growth_s_trial_takes_a_card_says_its_first_charge_and_is_had_once(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    workspace = acme["acme"]
    await _synced(stripe)
    _as(identity, acme, "admin")
    assert (await client.get(f"{API}/subscription")).json()["trial_available"] is True

    opened = await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "month"})
    quote = opened.json()["quote"]
    # Said before paying: 14 days, then the launch price on that day.
    assert (quote["trial_days"], quote["charged"], quote["then_monthly"]) == (14, 14320, 17900)
    assert quote["first_charge_on"] is not None
    [session] = stripe.posted("/v1/checkout/sessions")
    assert session["subscription_data[trial_period_days]"] == "14"
    assert session["payment_method_collection"] == "always"
    assert session["subscription_data[trial_settings][end_behavior][missing_payment_method]"] == (
        "cancel"
    )
    # Starter has none.
    await client.post(f"{API}/checkout", json={"plan": "starter", "interval": "month"})
    assert "subscription_data[trial_period_days]" not in stripe.posted("/v1/checkout/sessions")[-1]

    # Trialing: Growth, from the verified event only.
    stripe.subscriptions["sub_1"] = subscription("growth", "trialing")
    completed = _event(
        "checkout.session.completed",
        {
            "id": "cs_1",
            "mode": "subscription",
            "subscription": "sub_1",
            "customer": "cus_1",
            "client_reference_id": str(workspace),
        },
        created=1_800_000_100,
    )
    assert (await _deliver(client, completed)).json() == {"received": "plan:growth"}
    assert (await client.get(f"{API}/subscription")).json()["status"] == "trialing"
    # Converted at its end: paid, Growth still.
    converted = _event(
        "customer.subscription.updated", subscription("growth", "active"), created=1_800_000_200
    )
    assert (await _deliver(client, converted)).json() == {"received": "plan:growth"}
    paid = _event("invoice.paid", {"customer": "cus_1", "id": "in_1"}, created=1_800_000_210)
    assert (await _deliver(client, paid)).json() == {"received": "paid"}
    # A renewal that fails: held while Stripe retries, then unpaid — Free.
    retrying = _event(
        "customer.subscription.updated", subscription("growth", "past_due"), created=1_800_000_300
    )
    assert (await _deliver(client, retrying)).json() == {"received": "plan:growth"}
    unpaid = _event(
        "customer.subscription.updated", subscription("growth", "unpaid"), created=1_800_000_400
    )
    assert (await _deliver(client, unpaid)).json() == {"received": "plan:free"}
    assert await _plan(workspace) == "free"

    # Subscribed once: no second trial.
    said = (await client.get(f"{API}/subscription")).json()
    assert said["trial_available"] is False
    again = await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "month"})
    assert again.json()["quote"]["trial_days"] is None
    assert "subscription_data[trial_period_days]" not in stripe.posted("/v1/checkout/sessions")[-1]


@pytest.mark.integration
async def test_a_trial_cancelled_before_its_end_is_never_paid_for(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    workspace = acme["acme"]
    await _synced(stripe)
    _as(identity, acme, "admin")
    await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "month"})
    trialing = _event(
        "customer.subscription.created",
        {**subscription("growth", "trialing"), "metadata": {"workspace_id": str(workspace)}},
        created=1_800_000_100,
    )
    assert (await _deliver(client, trialing)).json() == {"received": "plan:growth"}
    # Cancelled in the portal before the 14 days: ended, never charged — Free.
    ended = _event(
        "customer.subscription.deleted", subscription("growth", "canceled"), created=1_800_000_200
    )
    assert (await _deliver(client, ended)).json() == {"received": "plan:free"}
    assert await _plan(workspace) == "free"
    # A checkout cancelled, or a browser back from it: nothing changes.
    assert (await client.get(f"{API}/subscription")).json()["plan"] == "free"


# ── no AI capacity sold ─────────────────────────────────────────────────────


@pytest.mark.integration
async def test_no_ai_capacity_is_sold_a_one_time_payment_credits_nothing(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    workspace = acme["acme"]
    _as(identity, acme, "admin")
    # No route sells it.
    assert (await client.post(f"{API}/capacity/checkout", json={"pack": "s"})).status_code in (
        404,
        405,
    )
    # Nor a payment made outside it: told, ignored, nothing credited.
    paid = {
        "id": "cs_pack",
        "mode": "payment",
        "payment_status": "paid",
        "customer": "cus_1",
        "client_reference_id": str(workspace),
        "metadata": {"leka_pack": "s", "leka_credits": "500", "workspace_id": str(workspace)},
    }
    told = _event("checkout.session.completed", paid, created=2)
    assert (await _deliver(client, told)).json() == {"received": "ignored"}
    assert await _count(workspace, CreditPack) == 0
    # Nothing in Stripe sells it either: the catalogue makes plans only.
    await _synced(stripe)
    assert not [p for p in stripe.posted("/v1/products") if "pack" in p["id"]]
