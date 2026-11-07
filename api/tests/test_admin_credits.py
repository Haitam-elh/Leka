"""The AI credits module of LEKA ADMIN (LEKA-553): every ledger line by line,
each month reconciled with the gateway, this month's capacity across
organisations, consumption by organisation, agent and model and the
providers' cost apart; an adjustment by LEKA's team allowed to the roles
that may, with its reason, written once, kept in both trails.
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.admin import AdminAuditEvent, AdminRole
from leka.capabilities import ModelCall
from leka.core.config import settings
from leka.db import session_factory, system_scope
from leka.governance import AuditEvent, CreditTransaction
from leka.metering import UsageRecord, post_ledger
from tests.test_admin_api import API, SUPER, World, as_, world  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


def _c(cost: float) -> float:
    return round(cost / settings.credit_usd, 4)


async def _consumed(world: World) -> uuid.UUID:
    """An execution of the owner's, metered at 0.40 dollars, and the
    gateway's call it was metered from, beside a call of the organisation's
    own model; the ledger posted. Returns the consumption's line."""
    run = f"agent_run:{uuid.uuid4()}"
    with system_scope():
        async with session_factory() as session:
            session.add_all(
                [
                    UsageRecord(
                        workspace_id=world.alpha,
                        execution=run,
                        kind="agent_run",
                        subject="code-review",
                        outcome="succeeded",
                        started_at=NOW - timedelta(minutes=30),
                        calls=1,
                        failed_calls=0,
                        invalid_calls=0,
                        retries=0,
                        fallbacks=0,
                        tool_calls=0,
                        unreported_calls=0,
                        latency_ms=0,
                        tokens_status="measured",
                        cost_status="estimated",
                        embedding_cost="not_applicable",
                        tool_cost="not_applicable",
                        infra_cost="not_applicable",
                        leka_cost_usd=0.4,
                        llm_cost_usd=0.4,
                        models=["google/gemini-2.5-pro"],
                        metered_at=NOW - timedelta(minutes=20),
                    ),
                    *(
                        ModelCall(
                            workspace_id=world.alpha,
                            purpose="agent:code-review",
                            tier="deep",
                            provider="google",
                            model="gemini-2.5-pro",
                            route="default",
                            owner=owner,
                            status="ok",
                            cost_usd=cost,
                            at=NOW - timedelta(minutes=30),
                        )
                        for owner, cost in (("leka", 0.4), ("workspace", 0.25))
                    ),
                ]
            )
            await session.flush()
            await post_ledger(session, world.alpha, now=NOW)
            await session.commit()
            line = await session.scalar(
                select(CreditTransaction.id).where(
                    CreditTransaction.workspace_id == world.alpha,
                    CreditTransaction.execution == run,
                )
            )
            assert line is not None
            return line


def _adjust(world: World, role: AdminRole, key: str, **body: Any) -> dict[str, Any]:
    return {
        "url": f"{API}/organisations/{world.alpha}/credits/adjustments",
        "json": {"reason": "credits given twice by mistake", **body},
        "headers": {**as_(world, role), "Idempotency-Key": f"{key}-{world.marker}"},
    }


async def test_an_adjustment_counts_at_once_is_written_once_and_kept_twice(
    client: AsyncClient, world: World
) -> None:
    before = (
        await client.get(f"{API}/organisations/{world.alpha}", headers=as_(world, SUPER))
    ).json()["credits"]
    done = await client.post(
        **_adjust(world, AdminRole.FINANCE, "adjust", kind="adjustment", credits=-300)
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["action"], body["replayed"]) == ("credits_adjusted", False)
    assert body["credits"]["adjustments"] == -300
    assert body["credits"]["allowance"] == before["allowance"] - 300
    again = await client.post(
        **_adjust(world, AdminRole.FINANCE, "adjust", kind="adjustment", credits=-300)
    )
    assert again.json()["replayed"] is True
    assert again.json()["credits"]["allowance"] == before["allowance"] - 300

    with system_scope():
        async with session_factory() as session:
            lines = (
                await session.scalars(
                    select(CreditTransaction).where(
                        CreditTransaction.workspace_id == world.alpha,
                        CreditTransaction.kind == "adjustment",
                    )
                )
            ).all()
            [kept] = (
                await session.scalars(
                    select(AdminAuditEvent).where(
                        AdminAuditEvent.action == "admin.credits_adjusted",
                        AdminAuditEvent.target_id == str(world.alpha),
                    )
                )
            ).all()
            customer = (
                await session.scalars(
                    select(AuditEvent.action).where(
                        AuditEvent.workspace_id == world.alpha,
                        AuditEvent.action == "workspace.credits_adjusted",
                    )
                )
            ).all()
    [line] = lines
    assert (float(line.credits), line.origin, line.reason) == (
        -300.0,
        "admin",
        "credits given twice by mistake",
    )
    assert line.by_whom == f"LEKA ADMIN finance-{world.marker}@leka.test"
    assert kept.detail["reason"] == "credits given twice by mistake"
    assert kept.detail["movement"] == str(line.id)
    assert len(customer) == 1


async def test_an_adjustment_is_for_the_roles_that_may_and_said_whole(
    client: AsyncClient, world: World
) -> None:
    refused = await client.post(
        **_adjust(world, AdminRole.SUPPORT, "support", kind="adjustment", credits=10)
    )
    assert refused.status_code == 403
    for name, body in {
        "none": {"kind": "adjustment", "credits": 0},
        "negative-refund": {"kind": "refund", "credits": -5},
        "no-reason": {"kind": "adjustment", "credits": 5, "reason": ""},
        "refund-of-nothing": {"kind": "adjustment", "credits": 5, "refund_of": str(uuid.uuid4())},
    }.items():
        response = await client.post(**_adjust(world, AdminRole.FINANCE, name, **body))
        assert response.status_code == 422, name
    no_key = await client.post(
        f"{API}/organisations/{world.alpha}/credits/adjustments",
        json={"kind": "adjustment", "credits": 5, "reason": "a gesture"},
        headers=as_(world, AdminRole.FINANCE),
    )
    assert no_key.status_code == 422


async def test_a_refund_gives_back_a_consumption_of_this_ledger_never_more(
    client: AsyncClient, world: World
) -> None:
    consumption = await _consumed(world)
    unknown = await client.post(
        **_adjust(
            world,
            AdminRole.FINANCE,
            "unknown",
            kind="refund",
            credits=5,
            refund_of=str(uuid.uuid4()),
        )
    )
    assert unknown.status_code == 404
    # 0.40 dollars is 40 credits: no more.
    too_much = await client.post(
        **_adjust(
            world, AdminRole.FINANCE, "much", kind="refund", credits=41, refund_of=str(consumption)
        )
    )
    assert too_much.status_code == 422
    given = await client.post(
        **_adjust(
            world, AdminRole.FINANCE, "given", kind="refund", credits=40, refund_of=str(consumption)
        )
    )
    assert given.status_code == 200, given.text
    movements = await client.get(
        f"{API}/credits/movements",
        params={"organisation_id": str(world.alpha), "kind": "refund"},
        headers=as_(world, AdminRole.FINANCE),
    )
    [refund] = movements.json()["data"]
    assert (refund["credits"], refund["origin"], refund["by"]) == (
        40.0,
        "admin",
        f"LEKA ADMIN finance-{world.marker}@leka.test",
    )


async def test_the_ledger_is_read_line_by_line(client: AsyncClient, world: World) -> None:
    await _consumed(world)
    response = await client.get(
        f"{API}/credits/movements",
        params={"organisation_id": str(world.alpha)},
        headers=as_(world, AdminRole.SUPPORT),
    )
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    # The latest first.
    assert [r["at"] for r in rows] == sorted((r["at"] for r in rows), reverse=True)
    kinds = {r["kind"] for r in rows}
    assert {"grant", "consumption"} <= kinds
    consumption = next(r for r in rows if r["kind"] == "consumption")
    assert (consumption["credits"], consumption["subject"], consumption["origin"]) == (
        -_c(0.4),
        "code-review",
        "metering",
    )
    assert (consumption["cost_usd"], consumption["cost_status"]) == (0.4, "estimated")
    assert consumption["reference"].startswith("use:agent_run:")
    grant = next(r for r in rows if r["kind"] == "grant")
    assert (grant["origin"], grant["organisation"]["id"]) == ("plan", str(world.alpha))
    month = NOW.strftime("%Y-%m")
    this_month = await client.get(
        f"{API}/credits/movements",
        params={"organisation_id": str(world.alpha), "period": month, "kind": "consumption"},
        headers=as_(world, AdminRole.SUPPORT),
    )
    assert [r["kind"] for r in this_month.json()["data"]] == ["consumption"]
    refused = await client.get(
        f"{API}/credits/movements", params={"period": "November"}, headers=as_(world, SUPER)
    )
    assert refused.status_code == 422


async def test_a_month_is_reconciled_with_the_gateway(client: AsyncClient, world: World) -> None:
    await _consumed(world)
    response = await client.get(
        f"{API}/organisations/{world.alpha}/credits/reconciliation",
        params={"months": 3},
        headers=as_(world, AdminRole.FINANCE),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    current = body["months"][0]
    assert current["period"] == NOW.strftime("%Y-%m")
    assert current["granted"] == settings.plan_credits["growth"]
    assert current["consumed"] == _c(0.4)
    assert current["source"] == _c(0.4)
    assert (current["pending"], current["allowance_gap"], current["reconciled"]) == (0.0, 0.0, True)
    assert current["by_subject"] == [{"subject": "code-review", "credits": _c(0.4)}]
    assert body["credits"]["allowance"] == current["allowance_now"]
    # A call the metering has not reached yet: pending, never guessed.
    with system_scope():
        async with session_factory() as session:
            session.add(
                ModelCall(
                    workspace_id=world.alpha,
                    purpose="intention.understanding",
                    tier="fast",
                    provider="google",
                    model="gemini-2.5-flash",
                    route="default",
                    owner="leka",
                    status="ok",
                    cost_usd=0.05,
                    at=NOW,
                )
            )
            await session.commit()
    later = await client.get(
        f"{API}/organisations/{world.alpha}/credits/reconciliation",
        headers=as_(world, AdminRole.FINANCE),
    )
    current = later.json()["months"][0]
    assert (current["pending"], current["reconciled"]) == (_c(0.05), False)
    unknown = await client.get(
        f"{API}/organisations/{uuid.uuid4()}/credits/reconciliation", headers=as_(world, SUPER)
    )
    assert unknown.status_code == 404


async def test_credits_across_leka_capacity_consumption_and_cost_apart(
    client: AsyncClient, world: World
) -> None:
    await _consumed(world)
    response = await client.get(
        f"{API}/credits/overview", params={"period": "7d"}, headers=as_(world, AdminRole.FINANCE)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    month = body["month"]
    assert month["period"] == NOW.strftime("%Y-%m")
    assert month["capacity"] == month["plans"] + month["packs"] + month["adjustments"]
    assert month["capacity"] >= settings.plan_credits["growth"]
    alpha = next(o for o in body["by_organisation"] if o["key"] == str(world.alpha))
    assert (alpha["credits"], alpha["cost_usd"]) == (_c(0.4), 0.4)
    assert any(a["key"] == "code-review" and a["credits"] >= _c(0.4) for a in body["by_agent"])
    assert any(m["key"] == "google/gemini-2.5-pro" for m in body["by_model"])
    assert len(body["series"]) in (7, 8)
    cost = body["provider_cost"]
    # LEKA's models and an organisation's own, apart: at the providers' rates.
    assert cost["basis"] == "rates"
    assert cost["leka_usd"] >= 0.4
    assert cost["workspace_usd"] >= 0.25
