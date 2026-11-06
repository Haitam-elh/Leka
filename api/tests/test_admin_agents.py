"""The agents module of LEKA ADMIN (LEKA-552): every agent of the registry,
each on its own, measured from its real runs — used how often and by how
many organisations, how well, how fast, what its runs used and cost at the
providers' rates (partial or unavailable, said so, never 0), what it brings
in when it is bought alone — ranked, filtered, beside the period before;
and one agent over a period.
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from leka.admin.agents import registry
from leka.billing import AgentEntitlement
from leka.billing import catalogue as offer_catalogue
from leka.capabilities import AgentRun
from leka.core.config import settings
from leka.db import session_factory, system_scope
from leka.metering import UsageRecord
from tests.test_admin_api import API, SUPER, World, as_, world  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


def _ago(**delta: float) -> datetime:
    return NOW - timedelta(**delta)


def _run(world: World, key: str, status: str, at: datetime, **said: Any) -> AgentRun:
    return AgentRun(
        workspace_id=world.alpha,
        id=uuid.uuid4(),
        key=key,
        version=said.pop("version", "1.0.0"),
        status=status,
        inputs={},
        requested_by=world.owner,
        format="markdown",
        detail={},
        queued_at=at,
        started_at=at,
        finished_at=at + timedelta(seconds=said.pop("seconds", 60)),
        **said,
    )


def _usage(run: AgentRun, cost_status: str, **said: Any) -> UsageRecord:
    record: dict[str, Any] = {
        "calls": 0,
        "failed_calls": 0,
        "invalid_calls": 0,
        "retries": 0,
        "fallbacks": 0,
        "tool_calls": 0,
        "unreported_calls": 0,
        "latency_ms": 0,
        "tokens_status": "measured",
        "embedding_cost": "not_applicable",
        "tool_cost": "not_applicable",
        "infra_cost": "not_applicable",
    }
    return UsageRecord(
        workspace_id=run.workspace_id,
        execution=f"agent_run:{run.id}",
        kind="agent_run",
        subject=run.key,
        outcome=run.status,
        started_at=run.queued_at,
        metered_at=NOW,
        cost_status=cost_status,
        **(record | said),
    )


async def _runs(world: World) -> str:
    """Beside the world's two code-review runs (never metered): security
    reviews, one priced and one not, and two before the period; data
    analyses never priced; a test analysis that called no model; a run of an
    agent no longer in the registry."""
    ghost = f"ghost-{world.marker}"
    priced = _run(world, "security-review", "succeeded", _ago(hours=2), model="gemini-2.5-pro")
    unpriced = _run(
        world,
        "security-review",
        "failed",
        _ago(hours=1),
        model="mistral-small",
        error="timeout",
        seconds=120,
    )
    early = _run(
        world,
        "security-review",
        "succeeded",
        _ago(days=10),
        model="gemini-2.5-pro",
        version="0.9.0",
    )
    earlier = _run(
        world,
        "security-review",
        "failed",
        _ago(days=11),
        model="gemini-2.5-pro",
        error="timeout",
        version="0.9.0",
    )
    data = _run(world, "data-analysis", "succeeded", _ago(hours=3))
    quiet = _run(world, "test-analysis", "succeeded", _ago(hours=4))
    gone = _run(world, ghost, "failed", _ago(hours=5), error="abandoned")
    with system_scope():
        async with session_factory() as session:
            session.add_all([priced, unpriced, early, earlier, data, quiet, gone])
            await session.flush()
            session.add_all(
                [
                    _usage(
                        priced,
                        "estimated",
                        calls=3,
                        tokens_in=1000,
                        tokens_out=200,
                        llm_cost_usd=0.04,
                        leka_cost_usd=0.03,
                    ),
                    _usage(unpriced, "unknown", calls=2, tokens_in=500, tokens_out=50),
                    _usage(early, "estimated", calls=1, llm_cost_usd=0.01, leka_cost_usd=0.01),
                    _usage(data, "partial", calls=1, tokens_in=10, tokens_out=1),
                    _usage(quiet, "none", tokens_status="none"),
                ]
            )
            await session.commit()
    return ghost


async def _agents(client: AsyncClient, world: World, **params: Any) -> dict[str, dict[str, Any]]:
    response = await client.get(
        f"{API}/agents",
        params={"organisation_id": str(world.alpha), **params},
        headers=as_(world, SUPER),
    )
    assert response.status_code == 200, response.text
    return {row["key"]: row for row in response.json()["data"]}


async def test_every_agent_of_the_registry_is_listed_each_on_its_own(
    client: AsyncClient, world: World
) -> None:
    ghost = await _runs(world)
    ran = await _agents(client, world)
    # By default, as before: the agents that ran.
    assert set(ran) == {"code-review", "security-review", "data-analysis", "test-analysis", ghost}
    every = await _agents(client, world, unused="true")
    known = registry()
    assert set(every) == set(known) | {ghost}
    never = next(k for k in sorted(known) if k not in ran)
    assert (every[never]["runs"], every[never]["cost_status"], every[never]["cost_usd"]) == (
        0,
        "none",
        None,
    )
    review = every["security-review"]
    definition = known["security-review"]
    assert (review["title"], review["category"], review["version"], review["lifecycle"]) == (
        definition.title,
        definition.category,
        definition.version,
        "active",
    )
    # An agent taken out of the registry still says what it did.
    assert (every[ghost]["title"], every[ghost]["lifecycle"], every[ghost]["failed"]) == (
        None,
        None,
        1,
    )
    drafts = await _agents(client, world, unused="true", lifecycle="draft")
    assert drafts and all(row["lifecycle"] == "draft" for row in drafts.values())


async def test_what_runs_used_and_cost_is_said_as_far_as_it_is_known(
    client: AsyncClient, world: World
) -> None:
    await _runs(world)
    agents = await _agents(client, world)
    review = agents["security-review"]
    assert (review["runs"], review["succeeded"], review["failed"], review["organisations"]) == (
        4,
        2,
        2,
        1,
    )
    assert review["success_rate"] == 0.5
    # One run of four priced at the providers' rates, one more not, two
    # with no line in the ledger yet: partial, the priced part only.
    assert (review["calls"], review["tokens_in"], review["tokens_out"]) == (6, 1500, 250)
    assert (review["cost_status"], review["unpriced_runs"]) == ("partial", 2)
    assert review["cost_usd"] == pytest.approx(0.05)
    assert review["credits"] == round(0.04 / settings.credit_usd, 2)
    # Never priced: unavailable, never 0.
    assert (agents["data-analysis"]["cost_status"], agents["data-analysis"]["cost_usd"]) == (
        "unavailable",
        None,
    )
    assert (agents["code-review"]["cost_status"], agents["code-review"]["cost_usd"]) == (
        "unavailable",
        None,
    )
    # No model called: measured, and nothing spent.
    assert (agents["test-analysis"]["cost_status"], agents["test-analysis"]["cost_usd"]) == (
        "measured",
        0.0,
    )


async def test_agents_are_filtered_and_ranked(client: AsyncClient, world: World) -> None:
    ghost = await _runs(world)
    on_gemini = await _agents(client, world, model="gemini-2.5-pro")
    assert set(on_gemini) == {"security-review"}
    assert (on_gemini["security-review"]["runs"], on_gemini["security-review"]["cost_status"]) == (
        3,
        "partial",
    )
    failed = await _agents(client, world, status="failed")
    assert {k: r["runs"] for k, r in failed.items()} == {
        "code-review": 1,
        "security-review": 2,
        ghost: 1,
    }
    recent = await _agents(client, world, since=_ago(days=1).isoformat())
    assert recent["security-review"]["runs"] == 2
    by_name = await _agents(client, world, organisation=f"alpha {world.marker}")
    assert by_name.keys() == (await _agents(client, world)).keys()

    async def keys(**params: str) -> list[str]:
        return list(await _agents(client, world, **params))

    assert (await keys())[0] == "security-review"
    assert (await keys(order="asc"))[-1] == "security-review"
    # The best rate first; the agents that never ended one, last.
    assert (await keys(sort="success_rate"))[:2] == ["data-analysis", "test-analysis"]
    assert (await keys(sort="success_rate"))[-1] == ghost
    # The costliest first; those whose cost is unknown last, whichever the order.
    costly = await keys(sort="cost")
    assert costly[:2] == ["security-review", "test-analysis"]
    assert set(costly[2:]) == {"code-review", "data-analysis", ghost}
    assert (await keys(sort="cost", order="asc"))[:2] == ["test-analysis", "security-review"]
    refused = await client.get(f"{API}/agents", params={"sort": "fame"}, headers=as_(world, SUPER))
    assert refused.status_code == 422


async def test_a_period_is_set_beside_the_one_before(client: AsyncClient, world: World) -> None:
    await _runs(world)
    agents = await _agents(
        client,
        world,
        period="custom",
        **{"from": _ago(days=7).isoformat(), "to": NOW.isoformat()},
    )
    review = agents["security-review"]
    assert (review["runs"], review["success_rate"]) == (2, 0.5)
    # The week before: the two runs of version 0.9.0.
    assert review["previous"] == {
        "runs": 2,
        "organisations": 1,
        "success_rate": 0.5,
        "cost_usd": pytest.approx(0.01),
    }
    assert agents["data-analysis"]["previous"]["runs"] == 0
    # No period asked: nothing to compare.
    assert (await _agents(client, world))["security-review"]["previous"] is None


async def test_revenue_is_an_agent_s_only_when_it_is_bought_alone(
    client: AsyncClient, world: World
) -> None:
    bundle = offer_catalogue().add_ons.bundles[0]
    member = bundle.agents[0]
    with system_scope():
        async with session_factory() as session:
            session.add_all(
                [
                    AgentEntitlement(
                        workspace_id=world.alpha,
                        key="security-review",
                        kind="agent",
                        origin="purchase",
                        by_whom="stripe",
                        started_at=_ago(days=3),
                        recurring={
                            "amount": 2500,
                            "currency": "eur",
                            "interval": "month",
                            "interval_count": 1,
                            "discount": {"percent_off": 20.0, "amount_off": None, "ends": None},
                        },
                    ),
                    # Bought, its price never said: not traceable.
                    AgentEntitlement(
                        workspace_id=world.alpha,
                        key="data-analysis",
                        kind="agent",
                        origin="purchase",
                        by_whom="stripe",
                        started_at=_ago(days=3),
                    ),
                    # Given, not sold.
                    AgentEntitlement(
                        workspace_id=world.alpha,
                        key="test-analysis",
                        kind="agent",
                        origin="grant",
                        by_whom="ops",
                        started_at=_ago(days=3),
                    ),
                    AgentEntitlement(
                        workspace_id=world.alpha,
                        key=bundle.key,
                        kind="bundle",
                        origin="purchase",
                        by_whom="stripe",
                        started_at=_ago(days=3),
                        recurring={"amount": 4900, "currency": "eur", "interval": "month"},
                    ),
                ]
            )
            await session.commit()
    agents = await _agents(client, world, unused="true")
    review = agents["security-review"]
    assert (review["revenue_eur"], review["purchases"]) == (20.0, 1)
    assert (agents["data-analysis"]["revenue_eur"], agents["data-analysis"]["purchases"]) == (
        None,
        1,
    )
    assert (agents["test-analysis"]["revenue_eur"], agents["test-analysis"]["purchases"]) == (
        None,
        0,
    )
    # A bundle's revenue is never split among its agents: counted, not priced.
    assert (agents[member]["bundle_purchases"], agents[member]["revenue_eur"]) == (1, None)
    ranked = list(await _agents(client, world, sort="revenue", unused="true"))
    assert ranked[0] == "security-review"


async def test_one_agent_over_a_period(client: AsyncClient, world: World) -> None:
    await _runs(world)
    response = await client.get(
        f"{API}/agents/security-review",
        params={"period": "30d", "organisation_id": str(world.alpha)},
        headers=as_(world, SUPER),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["stat"]["runs"], body["stat"]["previous"]["runs"]) == (4, 0)
    assert body["bucket"] == "day"
    assert len(body["series"]) in (30, 31)
    assert sum(p["runs"] for p in body["series"]) == 4
    assert sum(p["failed"] for p in body["series"]) == 2
    assert [(m["model"], m["runs"], m["failed"]) for m in body["models"]] == [
        ("gemini-2.5-pro", 3, 1),
        ("mistral-small", 1, 1),
    ]
    # Priced in part on one model, not at all on the other.
    assert body["models"][0]["cost_usd"] == pytest.approx(0.05)
    assert body["models"][1]["cost_usd"] is None
    assert [(v["version"], v["runs"]) for v in body["versions"]] == [("1.0.0", 2), ("0.9.0", 2)]
    [used] = body["organisations"]
    assert (used["organisation"]["id"], used["runs"], used["failed"]) == (str(world.alpha), 4, 2)
    assert [(f["error"], f["runs"]) for f in body["failures"]] == [("timeout", 2)]
    add_ons = offer_catalogue().add_ons
    offer = body["offer"]
    assert offer["tier"] == str(add_ons.agents["security-review"].tier)
    assert offer["monthly_price_eur"] == add_ons.prices["security-review"] / 100
    assert {b["key"] for b in offer["bundles"]} == {
        b.key for b in add_ons.bundles if "security-review" in b.agents
    }
    assert body["summary"] == registry()["security-review"].summary

    never = next(k for k in sorted(registry()) if k not in {"security-review", "code-review"})
    quiet = await client.get(f"{API}/agents/{never}", headers=as_(world, SUPER))
    assert quiet.status_code == 200
    assert quiet.json()["stat"]["runs"] >= 0
    unknown = await client.get(f"{API}/agents/nobody-{world.marker}", headers=as_(world, SUPER))
    assert unknown.status_code == 404
