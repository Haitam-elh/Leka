"""An agent's or a bundle's subscription cancelled, or renewed again
(LEKA-474: « Annuler l'abonnement » / « Réactiver le renouvellement ») — on a
Stripe whose API is faked, its webhooks signed as Stripe signs them.

What these protect:
- Cancelled from LEKA: at its period's end, said with its date — what it
  grants kept until then; renewed again, undone. Only the subscription it was
  bought with is asked of Stripe.
- Never another subscription: not the plan's, not another workspace's — and
  only who may change the workspace.
- Cancelled from Stripe's portal: said the same; the same event delivered
  twice applied once; at the period's end, or unpaid, or expired, no longer
  owned — a payment failing (past_due) keeps it while Stripe retries.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from leka.api import add_ons as add_ons_api
from tests.conftest import FakeIdentity
from tests.test_billing_renewal import Renewing, _subscribed
from tests.test_billing_stripe import FakeStripe, _deliver, _event, stripe, subscription
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

_ = stripe  # a fixture, requested by name
API = "/api/v1/billing"


@pytest.fixture
def renewing(stripe: FakeStripe, monkeypatch: pytest.MonkeyPatch) -> Renewing:
    fake = Renewing()
    fake.subscriptions = stripe.subscriptions
    monkeypatch.setattr(add_ons_api, "stripe", fake.client)
    return fake


def _marks(workspace: uuid.UUID) -> dict[str, str]:
    return {
        "workspace_id": str(workspace),
        "leka_add_on_kind": "agent",
        "leka_add_on_key": "security-review",
    }


async def _bought(client: AsyncClient, workspace: uuid.UUID, sub: str) -> None:
    """An agent paid for, its own subscription."""
    paid = await _deliver(
        client,
        _event(
            "checkout.session.completed",
            {
                "id": f"cs_{sub}",
                "mode": "subscription",
                "subscription": sub,
                "customer": "cus_1",
                "client_reference_id": str(workspace),
                "payment_status": "paid",
                "metadata": _marks(workspace),
            },
            created=int(time.time()) - 100,
        ),
    )
    assert paid.status_code == 200, paid.text


async def _owned(client: AsyncClient) -> list[dict[str, Any]]:
    found = (await client.get(f"{API}/entitlements")).json()
    return [e for e in found if e["origin"] == "purchase"]


async def test_cancelled_kept_until_its_end_then_renewed_again_only_its_own_subscription(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    renewing: Renewing,
) -> None:
    _as(identity, acme, "admin")
    await _bought(client, acme["acme"], "sub_agent")
    [agent] = await _owned(client)
    assert (agent["subscription"], agent["cancel_at_period_end"]) == ("sub_agent", False)

    stop = await client.post(f"{API}/add-ons/sub_agent/renewal", json={"renew": False})
    assert stop.status_code == 200, stop.text
    [said] = [e for e in stop.json() if e["origin"] == "purchase"]
    assert said["cancel_at_period_end"] is True
    assert said["current_period_end"].startswith("2030-03-17")
    # Kept until then: still owned.
    assert said["key"] == "security-review"
    assert renewing.asked == [
        ("POST", "/v1/subscriptions/sub_agent", {"cancel_at_period_end": "true"})
    ]

    again = await client.post(f"{API}/add-ons/sub_agent/renewal", json={"renew": True})
    assert again.status_code == 200, again.text
    assert (await _owned(client))[0]["cancel_at_period_end"] is False


async def test_never_the_plans_subscription_nor_another_workspaces(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    renewing: Renewing,
) -> None:
    _as(identity, acme, "admin")
    await _subscribed(client, acme["acme"], renewing)
    await _bought(client, acme["globex"], "sub_globex")

    for sub in ("sub_1", "sub_globex", "sub_unknown"):
        refused = await client.post(f"{API}/add-ons/{sub}/renewal", json={"renew": False})
        assert refused.status_code == 422, (sub, refused.text)
        assert refused.json()["error"]["details"][0]["message"] == "not_subscribed"
    # Nothing asked of Stripe.
    assert renewing.asked == []

    # Only who may change the workspace.
    await _bought(client, acme["acme"], "sub_agent")
    _as(identity, acme, "member")
    assert (
        await client.post(f"{API}/add-ons/sub_agent/renewal", json={"renew": False})
    ).status_code == 403


async def test_cancelled_from_stripes_portal_said_once_then_ended_as_stripe_says(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    renewing: Renewing,
) -> None:
    _as(identity, acme, "admin")
    await _bought(client, acme["acme"], "sub_agent")
    now = int(time.time())
    cancelled = subscription("growth", "active", sub="sub_agent")
    cancelled.update(cancel_at_period_end=True, metadata=_marks(acme["acme"]))
    event = _event("customer.subscription.updated", cancelled, created=now, event="evt_cancel")
    assert (await _deliver(client, event)).status_code == 200
    # Delivered again: applied once.
    again = await _deliver(client, event)
    assert again.status_code == 200
    [said] = await _owned(client)
    assert (said["cancel_at_period_end"], said["current_period_end"][:10]) == (True, "2030-03-17")

    # A payment failing: Stripe retries, the agent is kept meanwhile.
    late = dict(cancelled, status="past_due")
    assert (
        await _deliver(client, _event("customer.subscription.updated", late, created=now + 1))
    ).status_code == 200
    assert len(await _owned(client)) == 1

    # Its period ended: no longer owned.
    ended = dict(cancelled, status="canceled")
    assert (
        await _deliver(client, _event("customer.subscription.deleted", ended, created=now + 2))
    ).status_code == 200
    assert await _owned(client) == []


@pytest.mark.parametrize("status", ["unpaid", "incomplete_expired"])
async def test_unpaid_or_expired_no_longer_owned(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    renewing: Renewing,
    status: str,
) -> None:
    _as(identity, acme, "admin")
    await _bought(client, acme["acme"], "sub_agent")
    gone = subscription("growth", status, sub="sub_agent")
    gone["metadata"] = _marks(acme["acme"])
    assert (
        await _deliver(
            client, _event("customer.subscription.updated", gone, created=int(time.time()))
        )
    ).status_code == 200
    assert await _owned(client) == []
