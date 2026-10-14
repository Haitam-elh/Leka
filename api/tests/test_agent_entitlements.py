"""Agents paid for (2026-10-14, the product call: « un compte Free a utilisé
l'agent Architecte applicatif gratuitement ») — on a Stripe whose API is
faked, its webhooks signed as Stripe signs them.

Acme runs every agent, as LEKA's team's workspaces do; Globex is a customer.

What these protect:
- On Free, no agent runs — refused by the server, said why (`plan_required`)
  — and none is bought: the plan comes first.
- On Starter, an agent runs once bought — alone, or in a bundle; the others
  say `not_owned`. LEKA's grant runs every one.
- What is sold, read: each agent's tier and price, the bundles — their
  agents, their price against the agents alone — what this workspace owns.
- Bought: a Checkout at the catalogue's price, a subscription of its own;
  paid, owned — the plan untouched; cancelled, no longer. Opened from an
  intention's decision, its agents launched once paid; back where it was
  bought — the decision, or the new home's thread — never an address asked.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from leka.api import add_ons as add_ons_api
from leka.billing import AddOnCheckout, AgentEntitlement, owned
from leka.billing import add_ons as billing_add_ons
from leka.capabilities import sync_catalogue
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from leka.governance import set_plan
from tests.conftest import FakeIdentity
from tests.test_billing_stripe import SECRET, FakeStripe, _deliver, _event, _plan, stripe
from tests.test_capabilities_api import _connect
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

_ = stripe  # a fixture, requested by name
API = "/api/v1"


@pytest.fixture
def selling(stripe: FakeStripe, monkeypatch: pytest.MonkeyPatch) -> FakeStripe:
    """The add-ons' routes and module on the same fake Stripe."""
    configured = settings.model_copy(
        update={
            "stripe_secret_key": SecretStr("sk_test_fake"),
            "stripe_webhook_secret": SecretStr(SECRET),
            "web_url": "https://leka.test",
        }
    )
    monkeypatch.setattr(billing_add_ons, "settings", configured)
    monkeypatch.setattr(add_ons_api, "stripe", stripe.client)
    return stripe


async def _on(workspace: uuid.UUID, plan: str) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await set_plan(session, workspace, plan, by="tests", reason="a customer on it")
            await session.commit()


async def _why(client: AsyncClient, key: str) -> set[str]:
    """Why it may not run here, by what it pays for — no model configured
    in tests is said apart (`no_model`)."""
    found = (await client.get(f"{API}/capabilities/{key}")).json()
    return {r["code"] for r in found["reasons"]} & {"plan_required", "not_owned"}


async def test_on_free_no_agent_runs_nor_is_bought(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], selling: FakeStripe
) -> None:
    await sync_catalogue()
    await _connect({"acme": acme["globex"]}, "confluence")
    _as(identity, acme, "other_admin")
    assert await _why(client, "application-architecture") == {"plan_required"}
    # Refused by the server, not only a screen.
    started = await client.post(
        f"{API}/agent-runs",
        json={
            "key": "application-architecture",
            "inputs": {"parcours": "Paiement CB", "perimetre": "Digital"},
        },
    )
    assert (started.status_code, started.json()["error"]["code"]) == (422, "plan_required")
    sold = (await client.get(f"{API}/billing/add-ons")).json()
    assert (sold["plan"], sold["runs_agents"], sold["minimum_plan"]) == ("free", False, "starter")
    assert {a["why"] for a in sold["agents"]} == {"plan_required"}
    bought = await client.post(
        f"{API}/billing/add-ons/checkout", json={"kind": "agent", "key": "code-review"}
    )
    assert bought.status_code == 422
    assert bought.json()["error"]["details"][0]["message"] == "plan_required"


async def test_what_is_sold_its_prices_and_what_is_owned(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await sync_catalogue()
    _as(identity, acme, "member")
    sold = (await client.get(f"{API}/billing/add-ons")).json()
    agents = {a["key"]: a for a in sold["agents"]}
    assert (agents["application-architecture"]["tier"], agents["code-review"]["tier"]) == (
        "expert",
        "standard",
    )
    assert agents["application-architecture"]["monthly_price"] == 2500
    assert agents["code-review"]["monthly_price"] == 900
    assert "engineering" in agents["code-review"]["bundles"]
    engineering = next(b for b in sold["bundles"] if b["key"] == "engineering")
    assert engineering["agents"] == ["code-change", "code-review", "test-analysis", "build-fixer"]
    assert engineering["monthly_price"] < engineering["alone_price"]
    assert 0 < engineering["discount_percent"] <= 27
    # Acme: every agent, granted by LEKA.
    assert (sold["every"], sold["runs_agents"]) == (True, True)
    assert all(a["owned"] and a["why"] is None for a in sold["agents"])
    assert sold["provisional"] is True
    owned_ = (await client.get(f"{API}/billing/entitlements")).json()
    assert [(e["kind"], e["origin"]) for e in owned_] == [("all", "grant")]


async def test_bought_paid_owned_cancelled_no_longer_the_plan_untouched(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    selling: FakeStripe,
) -> None:
    await sync_catalogue()
    globex = acme["globex"]
    await _connect({"acme": globex}, "github")
    await _on(globex, "starter")
    _as(identity, acme, "other_admin")
    assert await _why(client, "code-review") == {"not_owned"}

    bought = await client.post(
        f"{API}/billing/add-ons/checkout", json={"kind": "bundle", "key": "engineering"}
    )
    assert bought.status_code == 200, bought.text
    assert bought.json()["url"] == "https://checkout.stripe.test/cs_1"
    [opened] = selling.posted("/v1/checkout/sessions")
    # The catalogue's price, a subscription of its own, marked as the bundle.
    assert opened["line_items[0][price_data][unit_amount]"] == "4500"
    assert opened["line_items[0][price_data][recurring][interval]"] == "month"
    assert opened["subscription_data[metadata][leka_add_on_key]"] == "engineering"
    assert opened["success_url"] == "https://leka.test/capabilities?bought=engineering"
    # Coming back from Checkout owns nothing: only Stripe's event does.
    assert await _why(client, "code-review") == {"not_owned"}

    marks = {
        "workspace_id": str(globex),
        "leka_add_on_kind": "bundle",
        "leka_add_on_key": "engineering",
    }
    now = int(time.time())
    paid = await _deliver(
        client,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_1",
                "mode": "subscription",
                "subscription": "sub_eng",
                "customer": "cus_1",
                "client_reference_id": str(globex),
                "metadata": marks,
            },
            created=now,
        ),
    )
    assert paid.status_code == 200, paid.text
    assert await _why(client, "code-review") == set()
    assert await _why(client, "application-architecture") == {"not_owned"}
    # The plan is the plan's: an add-on's events never touch it.
    assert await _plan(globex) == "starter"

    cancelled = await _deliver(
        client,
        _event(
            "customer.subscription.deleted",
            {"id": "sub_eng", "customer": "cus_1", "status": "canceled", "metadata": marks},
            created=now + 60,
        ),
    )
    assert cancelled.status_code == 200, cancelled.text
    assert await _why(client, "code-review") == {"not_owned"}
    assert await _plan(globex) == "starter"
    with workspace_scope(globex):
        async with session_factory() as session:
            [row] = (await session.scalars(select(AgentEntitlement))).all()
            assert (row.status, row.stripe_subscription_id) == ("ended", "sub_eng")


async def test_opened_from_a_decision_its_agents_are_launched_once_paid(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    selling: FakeStripe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await sync_catalogue()
    globex = acme["globex"]
    await _on(globex, "starter")
    _as(identity, acme, "other_admin")
    intention = uuid.uuid4()
    launch = [{"key": "code-review", "inputs": {}, "formats": []}]
    bought = await client.post(
        f"{API}/billing/add-ons/checkout",
        json={
            "kind": "agent",
            "key": "code-review",
            "intention_id": str(intention),
            "launch": launch,
        },
    )
    assert bought.status_code == 200, bought.text
    [opened] = selling.posted("/v1/checkout/sessions")
    assert (
        opened["success_url"]
        == f"https://leka.test/intentions/{intention}/decision?bought=code-review"
    )

    queued: list[tuple[Any, ...]] = []

    async def job(name: str, *args: Any, **kwargs: Any) -> object:
        queued.append((name, *args))
        return object()

    monkeypatch.setattr(billing_add_ons, "enqueue_job", job)
    marks = {
        "workspace_id": str(globex),
        "leka_add_on_kind": "agent",
        "leka_add_on_key": "code-review",
    }
    paid = await _deliver(
        client,
        _event(
            "checkout.session.completed",
            {"id": "cs_1", "mode": "subscription", "subscription": "sub_cr", "metadata": marks},
            created=int(time.time()),
        ),
    )
    assert paid.status_code == 200, paid.text
    with workspace_scope(globex):
        async with session_factory() as session:
            [row] = (await session.scalars(select(AddOnCheckout))).all()
            assert (row.status, row.intention_id, row.launch) == ("paid", intention, launch)
            assert (await owned(session, globex)).why("code-review") is None
    assert queued == [("leka.intentions.agents.run_bought_launch", str(globex), str(row.id))]


async def test_bought_from_the_new_home_s_thread_it_comes_back_to_it(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    selling: FakeStripe,
) -> None:
    await sync_catalogue()
    await _on(acme["globex"], "starter")
    _as(identity, acme, "other_admin")
    intention = uuid.uuid4()
    asked = {"kind": "agent", "key": "code-review", "intention_id": str(intention)}
    bought = await client.post(f"{API}/billing/add-ons/checkout", json={**asked, "back": "home"})
    assert bought.status_code == 200, bought.text
    [opened] = selling.posted("/v1/checkout/sessions")
    assert opened["success_url"] == f"https://leka.test/v2?i={intention}&bought=code-review"
    assert opened["cancel_url"] == f"https://leka.test/v2?i={intention}&bought=cancelled"
    # A choice, never an address the request names.
    elsewhere = await client.post(
        f"{API}/billing/add-ons/checkout", json={**asked, "back": "https://elsewhere.test"}
    )
    assert elsewhere.status_code == 422
