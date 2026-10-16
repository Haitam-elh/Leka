"""A subscription renewed, or not (2026-10-14, the product call: « Cancel
subscription », in English, that only stops the renewal; a service feared to
stop at the month's end) — on a Stripe whose API is faked, its webhooks
signed as Stripe signs them.

What these protect:
- « Ne pas renouveler »: the subscription kept until its period's end, said
  with its date; « Réactiver le renouvellement » undoes it. Only who may
  change the workspace; nothing to renew without a subscription.
- Renewed with nobody doing anything: its next period, paid — the plan
  stays, its new end said; the service never stops at the month's end.
- A webhook on Stripe's newer API, the period's end on its items: read all
  the same.
- Stripe's pages in the person's language: never « Cancel subscription » to
  someone who reads French.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from leka.api import subscriptions as subscriptions_api
from leka.billing import stripe_locale
from tests.conftest import FakeIdentity
from tests.test_billing_stripe import FakeStripe, _deliver, _event, _plan, stripe, subscription
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

_ = stripe  # a fixture, requested by name
API = "/api/v1/billing"
PERIOD_END = 1_900_000_000


class Renewing(FakeStripe):
    """Stripe's subscriptions, updated as LEKA asks."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.startswith("/v1/subscriptions/"):
            sub = path.removeprefix("/v1/subscriptions/")
            body = dict(httpx.QueryParams(request.content.decode()))
            self.asked.append((request.method, path, body))
            found = self.subscriptions.setdefault(sub, subscription("growth", "active", sub=sub))
            found["cancel_at_period_end"] = body.get("cancel_at_period_end") == "true"
            return httpx.Response(200, json=found)
        return super().__call__(request)


@pytest.fixture
def renewing(stripe: FakeStripe, monkeypatch: pytest.MonkeyPatch) -> Renewing:
    fake = Renewing()
    fake.subscriptions = stripe.subscriptions
    monkeypatch.setattr(subscriptions_api, "stripe", fake.client)
    return fake


async def _subscribed(client: AsyncClient, workspace: uuid.UUID, stripe: FakeStripe) -> None:
    stripe.subscriptions["sub_1"] = subscription("growth", "active")
    done = await _deliver(
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
            created=int(time.time()) - 100,
        ),
    )
    assert done.status_code == 200, done.text


async def test_not_renewed_kept_until_its_end_then_renewed_again(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    renewing: Renewing,
) -> None:
    _as(identity, acme, "admin")
    await _subscribed(client, acme["acme"], renewing)

    stop = await client.post(f"{API}/subscription/renewal", json={"renew": False})
    assert stop.status_code == 200, stop.text
    said = stop.json()
    assert said["cancel_at_period_end"] is True
    assert said["current_period_end"].startswith("2030-03-17")
    # Kept until then: the plan is still the plan.
    assert (said["plan"], said["status"]) == ("growth", "active")
    assert renewing.posted("/v1/subscriptions/sub_1")[-1] == {"cancel_at_period_end": "true"}

    again = await client.post(f"{API}/subscription/renewal", json={"renew": True})
    assert again.status_code == 200, again.text
    assert again.json()["cancel_at_period_end"] is False

    # Only who may change the workspace.
    _as(identity, acme, "member")
    refused = await client.post(f"{API}/subscription/renewal", json={"renew": False})
    assert refused.status_code == 403


async def test_nothing_to_renew_without_a_subscription(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    renewing: Renewing,
) -> None:
    _as(identity, acme, "admin")
    refused = await client.post(f"{API}/subscription/renewal", json={"renew": False})
    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0]["message"] == "not_subscribed"


async def test_renewed_with_nobody_doing_anything_the_service_goes_on(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    renewing: Renewing,
) -> None:
    _as(identity, acme, "admin")
    await _subscribed(client, acme["acme"], renewing)
    now = int(time.time())
    # The month ends: Stripe charges the next one and says so.
    paid = await _deliver(
        client,
        _event(
            "invoice.paid",
            {"id": "in_2", "customer": "cus_1", "subscription": "sub_1"},
            created=now,
        ),
    )
    assert paid.status_code == 200
    next_period = subscription("growth", "active")
    next_period["current_period_end"] = PERIOD_END + 30 * 86_400
    updated = await _deliver(
        client, _event("customer.subscription.updated", next_period, created=now + 1)
    )
    assert updated.status_code == 200
    said = (await client.get(f"{API}/subscription")).json()
    assert (said["plan"], said["status"], said["last_invoice"]) == ("growth", "active", "paid")
    assert said["current_period_end"].startswith("2030-04-16")
    assert await _plan(acme["acme"]) == "growth"


async def test_a_webhook_on_stripe_s_newer_api_says_its_end_on_its_items(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    renewing: Renewing,
) -> None:
    _as(identity, acme, "admin")
    await _subscribed(client, acme["acme"], renewing)
    newer: dict[str, Any] = subscription("growth", "active")
    del newer["current_period_end"]
    newer["items"]["data"][0]["current_period_end"] = PERIOD_END + 86_400
    done = await _deliver(
        client, _event("customer.subscription.updated", newer, created=int(time.time()) + 5)
    )
    assert done.status_code == 200
    said = (await client.get(f"{API}/subscription")).json()
    assert said["current_period_end"].startswith("2030-03-18")


async def test_stripe_s_pages_speak_the_person_s_language(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    renewing: Renewing,
) -> None:
    assert (stripe_locale("fr"), stripe_locale("en-GB"), stripe_locale("tlh")) == (
        "fr",
        "en",
        "auto",
    )
    _as(identity, acme, "admin")
    await _subscribed(client, acme["acme"], renewing)
    opened = await client.post(f"{API}/portal")
    assert opened.status_code == 200, opened.text
    [asked] = renewing.posted("/v1/billing_portal/sessions")
    assert asked["locale"] in ("fr", "en")
