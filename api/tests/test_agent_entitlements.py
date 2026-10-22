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
  intention's decision, its agents launched once paid.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import importlib
import time
import uuid
from typing import Any

import pytest
import yaml
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
from tests.test_billing_stripe import (
    SECRET,
    FakeStripe,
    _deliver,
    _event,
    _plan,
    _synced,
    stripe,
)
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


def _offer(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, change: Any) -> None:
    """The catalogue LEKA ships, changed for one test — read again after."""
    raw = yaml.safe_load(billing_catalogue.CATALOGUE_FILE.read_text(encoding="utf-8"))
    change(raw["add_ons"])
    path = tmp_path / "catalogue.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(billing_catalogue, "CATALOGUE_FILE", path)
    billing_catalogue.catalogue.cache_clear()


@pytest.fixture(autouse=True)
def _shipped() -> Any:
    """The shipped catalogue again after each test."""
    yield
    billing_catalogue.catalogue.cache_clear()


# The module, not the function the package exports under its name.
billing_catalogue = importlib.import_module("leka.billing.catalogue")

# A bundle every member of which is built, neither in Starter: sold
# (LEKA-454).
PAIR = {
    "key": "review-pair",
    "name": {"fr": "Revue", "en": "Review"},
    "members": ["security-reviewer", "incident-investigator"],
    "monthly_price": 4500,
}


async def _on(workspace: uuid.UUID, plan: str) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await set_plan(session, workspace, plan, by="tests", reason="a customer on it")
            await session.commit()


async def _why(client: AsyncClient, key: str) -> set[str]:
    """Why it may not run here, by what it pays for — no model configured
    in tests is said apart (`no_model`)."""
    found = (await client.get(f"{API}/capabilities/{key}")).json()
    return {r["code"] for r in found["reasons"]} & {"plan_required", "not_owned", "not_for_sale"}


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
    # Its name in the marketplace reference (LEKA-454).
    assert agents["application-architecture"]["reference"] == "Architect"
    assert "engineering" in agents["code-review"]["bundles"]
    engineering = next(b for b in sold["bundles"] if b["key"] == "engineering")
    # As the reference composes it, every one of its agents built (LEKA-461):
    # sold; its saving computed from its members' prices.
    assert len(engineering["agents"]) == 7
    assert [m["agent"] for m in engineering["members"]].count(None) == 0
    assert (engineering["sellable"], engineering["monthly_price"]) == (True, 5900)
    assert (engineering["alone_price"], engineering["discount_percent"]) == (9100, 35)
    ship_safe = next(b for b in sold["bundles"] if b["key"] == "ship-safe")
    # Some of its agents not built — Migration Planner, with no price: not
    # sold, no saving shown.
    assert ship_safe["sellable"] is False
    assert (ship_safe["alone_price"], ship_safe["discount_percent"]) == (None, None)
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
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    _offer(monkeypatch, tmp_path, lambda a: a["bundles"].append(PAIR))
    await sync_catalogue()
    globex = acme["globex"]
    await _connect({"acme": globex}, "github")
    await _on(globex, "starter")
    _as(identity, acme, "other_admin")
    assert await _why(client, "security-review") == {"not_owned"}

    # Not in Stripe yet: refused, never a price made up.
    unsynced = await client.post(
        f"{API}/billing/add-ons/checkout", json={"kind": "bundle", "key": "review-pair"}
    )
    assert unsynced.json()["error"]["details"][0]["message"] == "not_synced"
    await _synced(selling)
    bought = await client.post(
        f"{API}/billing/add-ons/checkout", json={"kind": "bundle", "key": "review-pair"}
    )
    assert bought.status_code == 200, bought.text
    assert bought.json()["url"] == "https://checkout.stripe.test/cs_1"
    [opened] = selling.posted("/v1/checkout/sessions")
    # Its Stripe price (LEKA-461), a subscription of its own, marked as the bundle.
    assert (
        opened["line_items[0][price]"] == selling.prices["leka_addon_bundle_review-pair_month_4500"]
    )
    assert opened["subscription_data[metadata][leka_add_on_key]"] == "review-pair"
    assert opened["success_url"] == "https://leka.test/capabilities?bought=review-pair"
    # Coming back from Checkout owns nothing: only Stripe's event does.
    assert await _why(client, "security-review") == {"not_owned"}

    marks = {
        "workspace_id": str(globex),
        "leka_add_on_kind": "bundle",
        "leka_add_on_key": "review-pair",
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
                "payment_status": "paid",
                "metadata": marks,
            },
            created=now,
        ),
    )
    assert paid.status_code == 200, paid.text
    assert await _why(client, "security-review") == set()
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
    assert await _why(client, "security-review") == {"not_owned"}
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
    await _synced(selling)
    intention = uuid.uuid4()
    launch = [{"key": "security-review", "inputs": {}, "formats": []}]
    bought = await client.post(
        f"{API}/billing/add-ons/checkout",
        json={
            "kind": "agent",
            "key": "security-review",
            "intention_id": str(intention),
            "launch": launch,
        },
    )
    assert bought.status_code == 200, bought.text
    [opened] = selling.posted("/v1/checkout/sessions")
    assert (
        opened["success_url"] == f"https://leka.test/intentions/{intention}?bought=security-review"
    )

    queued: list[tuple[Any, ...]] = []

    async def job(name: str, *args: Any, **kwargs: Any) -> object:
        queued.append((name, *args))
        return object()

    monkeypatch.setattr(billing_add_ons, "enqueue_job", job)
    marks = {
        "workspace_id": str(globex),
        "leka_add_on_kind": "agent",
        "leka_add_on_key": "security-review",
    }
    paid = await _deliver(
        client,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_1",
                "mode": "subscription",
                "subscription": "sub_cr",
                "payment_status": "paid",
                "metadata": marks,
            },
            created=int(time.time()),
        ),
    )
    assert paid.status_code == 200, paid.text
    with workspace_scope(globex):
        async with session_factory() as session:
            [row] = (await session.scalars(select(AddOnCheckout))).all()
            assert (row.status, row.intention_id, row.launch) == ("paid", intention, launch)
            assert (await owned(session, globex)).why("security-review") is None
    assert queued == [("leka.intentions.agents.run_bought_launch", str(globex), str(row.id))]


async def test_a_bundle_whose_agents_are_not_all_built_is_never_sold(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    selling: FakeStripe,
) -> None:
    await sync_catalogue()
    await _on(acme["globex"], "growth")
    _as(identity, acme, "other_admin")
    refused = await client.post(
        f"{API}/billing/add-ons/checkout", json={"kind": "bundle", "key": "ship-safe"}
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0]["message"] == "not_sold"
    assert selling.posted("/v1/checkout/sessions") == []
    # An agent of the registry the catalogue does not sell: never available.
    assert await _why(client, "map-service-ownership") == {"not_for_sale"}


async def test_an_agent_its_plan_includes_runs_without_an_option_and_no_longer_below_it(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    selling: FakeStripe,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    _offer(monkeypatch, tmp_path, lambda a: a.update(included={"growth": ["code-review"]}))
    await sync_catalogue()
    globex = acme["globex"]
    await _connect({"acme": globex}, "github")
    await _on(globex, "growth")
    _as(identity, acme, "other_admin")
    assert await _why(client, "code-review") == set()
    sold = {a["key"]: a for a in (await client.get(f"{API}/billing/add-ons")).json()["agents"]}
    assert (sold["code-review"]["included"], sold["code-review"]["owned"]) == (True, True)
    # Its category in the marketplace, the reference's (LEKA-467).
    assert (sold["code-review"]["market"], sold["build-fixer"]["market"]) == (
        "architecture",
        "incident",
    )
    # Included: nothing to buy.
    bought = await client.post(
        f"{API}/billing/add-ons/checkout", json={"kind": "agent", "key": "code-review"}
    )
    assert bought.json()["error"]["details"][0]["message"] == "owned"
    # Its plan ended — back on Free: no longer.
    await _on(globex, "free")
    assert await _why(client, "code-review") == {"plan_required"}


async def test_granted_only_once_stripe_confirms_the_payment(
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
    marks = {
        "workspace_id": str(globex),
        "leka_add_on_kind": "agent",
        "leka_add_on_key": "security-review",
    }
    now = int(time.time())
    session = {"id": "cs_9", "mode": "subscription", "subscription": "sub_9", "metadata": marks}
    # A payment still processing: nothing granted.
    waiting = await _deliver(
        client,
        _event("checkout.session.completed", {**session, "payment_status": "unpaid"}, created=now),
    )
    assert waiting.json() == {"received": "not_paid"}
    assert await _why(client, "security-review") == {"not_owned"}
    # Confirmed: granted.
    confirmed = await _deliver(
        client,
        _event(
            "checkout.session.async_payment_succeeded",
            {**session, "payment_status": "paid"},
            created=now + 5,
        ),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert await _why(client, "security-review") == set()
    # Its subscription's creation, delivered late — still « incomplete » as it
    # was made, before its payment (seen on Stripe's test mode, 2026-10-15):
    # what was paid for is kept.
    made = {"id": "sub_9", "customer": "cus_1", "status": "incomplete", "metadata": marks}
    late = await _deliver(client, _event("customer.subscription.created", made, created=now + 1))
    assert late.json() == {"received": "add_on_kept"}
    assert await _why(client, "security-review") == set()
    # A renewal failing: kept while Stripe retries (past_due) …
    retried = {"id": "sub_9", "customer": "cus_1", "status": "past_due", "metadata": marks}
    kept = await _deliver(
        client, _event("customer.subscription.updated", retried, created=now + 60)
    )
    assert kept.json() == {"received": "add_on_kept"}
    assert await _why(client, "security-review") == set()
    # … ended once Stripe gives up (unpaid): no right without a payment.
    unpaid = {**retried, "status": "unpaid"}
    ended = await _deliver(
        client, _event("customer.subscription.updated", unpaid, created=now + 120)
    )
    assert ended.json() == {"received": "add_on_ended:1"}
    assert await _why(client, "security-review") == {"not_owned"}


async def test_each_plan_runs_the_agents_it_includes_and_those_of_the_plans_below(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
) -> None:
    await sync_catalogue()
    globex = acme["globex"]
    await _connect({"acme": globex}, "github")
    _as(identity, acme, "other_admin")
    # Karim, 2026-10-15: Starter three; Growth those and five more; Business
    # all thirteen. What a plan does not include is an option.
    await _on(globex, "starter")
    assert await _why(client, "code-review") == set()
    assert await _why(client, "debug-assistant") == {"not_owned"}
    assert await _why(client, "security-review") == {"not_owned"}
    await _on(globex, "growth")
    assert await _why(client, "code-review") == set()
    assert await _why(client, "debug-assistant") == set()
    assert await _why(client, "security-review") == {"not_owned"}
    await _on(globex, "business")
    assert await _why(client, "security-review") == set()
    sold = (await client.get(f"{API}/billing/add-ons")).json()
    # Business includes every agent of Karim's matrix (15/10); Frontend
    # Craft's and Engineering's, built after it (LEKA-461), stay options
    # until he says.
    frontend = {
        "ui-quality-review",
        "accessibility-audit",
        "design-review",
        "motion-review",
        "codebase-explorer",
        "test-generation",
        "regression-analysis",
        "change-impact-analysis",
        # Acceptance (2026-10-21), the same until he says.
        "qa-acceptance",
        # API review (2026-10-22), the same.
        "api-design-review",
        # Reliability (2026-10-22): Incident Response's and Security & Reliability's.
        "reliability-analysis",
        # Dependencies (2026-10-22): Incident Response's and Security & Reliability's.
        "dependency-analysis",
        # Databases (2026-10-22): Security & Reliability's.
        "database-review",
    }
    assert all(a["included"] for a in sold["agents"] if a["key"] not in frontend)
    assert not any(a["included"] for a in sold["agents"] if a["key"] in frontend)
    # Free runs none.
    await _on(globex, "free")
    assert await _why(client, "code-review") == {"plan_required"}
    # Whatever its plan, each agent says the least plan that includes it.
    sold = (await client.get(f"{API}/billing/add-ons")).json()
    assert not any(a["included"] for a in sold["agents"])
    since = {a["key"]: a["included_from"] for a in sold["agents"]}
    assert (since["code-review"], since["debug-assistant"], since["security-review"]) == (
        "starter",
        "growth",
        "business",
    )
