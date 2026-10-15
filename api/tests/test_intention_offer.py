"""What carrying an intention through costs, said before anything is bought
(LEKA-458) — its analysis scripted (Gemini proposes the Architect), Stripe
faked.

What these protect:
- Each proposed agent as the plan said runs it: included (LEKA's grant,
  or the plan's own, Karim's matrix), owned, to buy at the catalogue's
  price — never shown included when it is not.
- The plan that carries it for least: on Free, agents need Starter — its
  price with the launch offer, for how long, and the price after it; the
  plan kept when it suffices; what it includes never sold with it. The
  lines and their total, now and after.
- The month's capacity measured, the agents' estimated; spent: blocked,
  the next plan offered — never an overage.
- Bought from the intention: the plan's checkout and several agents in one,
  each back to the intention's page; paid, each agent owned; ended, none.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import importlib
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from leka.api import add_ons as add_ons_api
from leka.api import subscriptions as subscriptions_api
from leka.billing import add_ons as billing_add_ons
from leka.billing import end
from leka.billing import subscriptions as billing_subscriptions
from leka.billing.entitlements import EVERY
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from leka.governance import set_plan
from leka.intentions import offer as offer_module
from leka.intentions.schemas import CreditsLeftRead
from tests.conftest import FakeIdentity
from tests.test_agent_entitlements import _offer as _catalogued
from tests.test_agent_runs_api import _ready
from tests.test_billing_stripe import SECRET, FakeStripe, _deliver, _event, _synced, stripe
from tests.test_context_engine import model
from tests.test_intention_agents import ARCHITECT, Gemini, _proposed, gemini, started
from tests.test_intention_analysis_api import API, queued  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

pytestmark = pytest.mark.integration

_ = (model, gemini, started, stripe)  # fixtures, requested by name


async def _on(workspace: uuid.UUID, plan: str, *, ungranted: bool = True) -> None:
    """A customer on `plan`: LEKA's grant of every agent taken back."""
    with workspace_scope(workspace):
        async with session_factory() as session:
            if ungranted:
                await end(session, workspace, key=EVERY)
            await set_plan(session, workspace, plan, by="tests", reason="a customer")
            await session.commit()


async def _offer(client: AsyncClient, intention: str, **params: str) -> dict[str, Any]:
    response = await client.get(f"{API}/{intention}/offer", params=params)
    assert response.status_code == 200, response.text
    said: dict[str, Any] = response.json()
    return said


@pytest.fixture
def paying(stripe: FakeStripe, monkeypatch: pytest.MonkeyPatch) -> FakeStripe:
    configured = settings.model_copy(
        update={
            "stripe_secret_key": SecretStr("sk_test_fake"),
            "stripe_webhook_secret": SecretStr(SECRET),
            "web_url": "https://leka.test",
        }
    )
    monkeypatch.setattr(billing_add_ons, "settings", configured)
    monkeypatch.setattr(billing_subscriptions, "settings", configured)
    monkeypatch.setattr(add_ons_api, "stripe", stripe.client)
    monkeypatch.setattr(subscriptions_api, "stripe", stripe.client)
    return stripe


async def test_granted_every_agent_nothing_to_buy(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    said = await _offer(client, intention["id"])
    [agent] = said["agents"]
    assert (agent["key"], agent["status"], agent["chosen"]) == (ARCHITECT, "included", True)
    assert (said["ready"], said["lines"], said["total_monthly"]) == (True, [], 0)


async def test_on_free_the_least_plan_and_the_agent_priced_now_and_after(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    await _on(acme["acme"], "free")
    said = await _offer(client, intention["id"])

    [agent] = said["agents"]
    # Never shown included: an option, at the catalogue's price.
    assert (agent["status"], agent["monthly_price"], agent["tier"]) == ("to_buy", 2500, "expert")
    # The least plan that runs agents: Starter, not the dearest.
    assert (said["plan_now"], said["plan"]["key"], said["change_plan"]) == ("free", "starter", True)
    plan, option = said["lines"]
    # The launch offer said with its length and the price after it.
    assert (plan["kind"], plan["monthly_price"], plan["then_monthly"], plan["for_months"]) == (
        "plan",
        4720,
        5900,
        12,
    )
    assert (option["kind"], option["key"], option["monthly_price"]) == ("agent", ARCHITECT, 2500)
    assert (said["total_monthly"], said["then_monthly"]) == (7220, 8400)
    assert said["ready"] is False
    # The month measured; the agent's run estimated — unknown before it ran.
    assert said["used"] >= 0 and said["estimate"] is None

    # None chosen: the plan alone carries what is left — nothing to buy.
    bare = await _offer(client, intention["id"], agents="")
    assert (bare["change_plan"], bare["lines"], bare["ready"]) == (False, [], True)


# The module, not the function the package exports under its name.
billing_catalogue = importlib.import_module("leka.billing.catalogue")


async def test_what_the_plan_includes_is_never_sold_with_it(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    _catalogued(monkeypatch, tmp_path, lambda a: a.update(included={"starter": [ARCHITECT]}))
    try:
        await _ready(acme)
        gemini()
        _as(identity, acme, "member")
        intention = await _proposed(client, acme)
        await _on(acme["acme"], "free")
        said = await _offer(client, intention["id"])
        # Starter includes it: the plan alone, the agent said included.
        [agent] = said["agents"]
        assert (agent["status"], said["plan"]["key"]) == ("included", "starter")
        assert [line["kind"] for line in said["lines"]] == ["plan"]
        assert (said["total_monthly"], said["then_monthly"]) == (4720, 5900)
    finally:
        billing_catalogue.catalogue.cache_clear()


async def test_on_starter_owning_it_launched_as_it_is(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    await _on(acme["acme"], "starter")
    said = await _offer(client, intention["id"])
    # On Starter, the plan suffices: only the option.
    assert (said["change_plan"], [line["kind"] for line in said["lines"]]) == (False, ["agent"])
    assert said["then_monthly"] is None


async def test_several_agents_bought_together_back_to_the_intention_each_owned(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    paying: FakeStripe,
) -> None:
    await _on(acme["globex"], "starter", ungranted=False)
    _as(identity, acme, "other_admin")
    intention = uuid.uuid4()
    keys = f"{ARCHITECT},code-review"
    bought = await client.post(
        "/api/v1/billing/add-ons/checkout",
        json={"kind": "agents", "key": keys, "intention_id": str(intention)},
    )
    assert bought.status_code == 200, bought.text
    [opened] = paying.posted("/v1/checkout/sessions")
    # One subscription, a line each, at the catalogue's prices.
    assert opened["line_items[0][price_data][unit_amount]"] == "2500"
    assert opened["line_items[1][price_data][unit_amount]"] == "900"
    assert opened["subscription_data[metadata][leka_add_on_kind]"] == "agents"
    assert opened["success_url"] == f"https://leka.test/intentions/{intention}?bought={keys}"

    marks = {
        "workspace_id": str(acme["globex"]),
        "leka_add_on_kind": "agents",
        "leka_add_on_key": keys,
    }
    now = int(time.time())
    paid = await _deliver(
        client,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_1",
                "mode": "subscription",
                "subscription": "sub_two",
                "payment_status": "paid",
                "metadata": marks,
            },
            created=now,
        ),
    )
    assert paid.status_code == 200, paid.text
    rights = (await client.get("/api/v1/billing/entitlements")).json()
    assert sorted(r["key"] for r in rights) == [ARCHITECT, "code-review"]
    ended = await _deliver(
        client,
        _event(
            "customer.subscription.deleted",
            {"id": "sub_two", "status": "canceled", "metadata": marks},
            created=now + 60,
        ),
    )
    assert ended.json() == {"received": "add_on_ended:2"}
    assert (await client.get("/api/v1/billing/entitlements")).json() == []


async def test_the_plan_bought_from_the_intention_comes_back_to_it(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    paying: FakeStripe,
) -> None:
    await _synced(paying)
    _as(identity, acme, "other_admin")
    intention = uuid.uuid4()
    opened = await client.post(
        "/api/v1/billing/checkout",
        json={"plan": "starter", "interval": "month", "intention_id": str(intention)},
    )
    assert opened.status_code == 200, opened.text
    made = paying.posted("/v1/checkout/sessions")[-1]
    assert made["success_url"] == f"https://leka.test/intentions/{intention}?activated=success"
    assert made["cancel_url"] == f"https://leka.test/intentions/{intention}?activated=cancelled"


async def test_the_month_spent_is_blocked_and_the_next_plan_offered_never_an_overage(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    await _on(acme["acme"], "starter")

    async def spent(*_: Any, **__: Any) -> CreditsLeftRead:
        return CreditsLeftRead(
            plan="starter",
            allowance=2000,
            used=2000.0,
            remaining=0.0,
            state="exhausted",
            enforced=True,
            period_end=datetime(2026, 11, 1, tzinfo=UTC),
        )

    monkeypatch.setattr(offer_module, "credits_left", spent)
    said = await _offer(client, intention["id"])
    assert (said["blocked"], said["ready"]) == ("credits_exhausted", False)
    # The next plan, which holds more — its line with the option; nothing
    # sold apart.
    assert (said["change_plan"], said["plan"]["key"]) == (True, "growth")
    assert [line["kind"] for line in said["lines"]] == ["plan", "agent"]
