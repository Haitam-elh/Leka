"""LEKA's internal metering reports (LEKA-430), against the database.

What these protect: an agent's cost a run — average, P50, P90, P95 — and an
intention's, end to end, read across workspaces; an execution counted on the
plan its workspace was on when it ran; the margin of a plan at its list and
its promotional price, none when it has no price; what was spent on answers
not asked for and on tries past the first, by purpose; two periods compared,
the change said; and the command writing them as CSV.

Every row is in January 2020: no other test's data is in that month.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import WorkspacePlan
from leka.metering import UsageRecord, cli, reports
from leka.platform import Workspace

pytestmark = pytest.mark.integration

MONTH = date(2020, 1, 1)
START = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
async def two() -> AsyncIterator[list[uuid.UUID]]:
    made = []
    with system_scope():
        async with session_factory() as session:
            for name in ("Reported A", "Reported B"):
                found = Workspace(name=name, slug=f"reported-{uuid.uuid4().hex[:10]}")
                session.add(found)
                await session.flush()
                made.append(found.id)
            await session.commit()
    yield made
    with system_scope():
        async with session_factory() as session:
            for ident in made:
                leftover = await session.get(Workspace, ident)
                if leftover is not None:
                    await session.delete(leftover)
            await session.commit()


def _record(workspace_id: uuid.UUID, cost: float | None, **fields: Any) -> UsageRecord:
    base: dict[str, Any] = {
        "workspace_id": workspace_id,
        "id": uuid.uuid4(),
        "execution": f"agent_run:{uuid.uuid4()}",
        "kind": "agent_run",
        "subject": "application-architecture",
        "outcome": "succeeded",
        "started_at": START + timedelta(days=3),
        "calls": 2,
        "failed_calls": 0,
        "invalid_calls": 0,
        "retries": 0,
        "fallbacks": 0,
        "tool_calls": 0,
        "unreported_calls": 0,
        "latency_ms": 1000,
        "tokens_in": 1000,
        "tokens_out": 200,
        "tokens_status": "measured",
        "llm_cost_usd": cost,
        "leka_cost_usd": cost,
        "cost_status": "estimated" if cost is not None else "unknown",
        "embedding_cost": "not_applicable",
        "tool_cost": "unavailable",
        "infra_cost": "unavailable",
        "metered_at": START,
    }
    return UsageRecord(**{**base, **fields})


async def _keep(workspace_id: uuid.UUID, *rows: Any) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            session.add_all(rows)
            await session.commit()


async def _read(act: Any) -> Any:
    with system_scope():
        async with session_factory() as session:
            return await act(session)


async def test_an_agent_s_cost_a_run_and_an_intention_s_end_to_end(two: list[uuid.UUID]) -> None:
    agent = f"agent-{uuid.uuid4().hex[:8]}"
    intention = uuid.uuid4()
    await _keep(
        two[0],
        *(_record(two[0], n / 100, subject=agent) for n in range(1, 11)),
        _record(two[0], None, subject=agent, cost_status="unknown"),
        _record(two[0], 0.20, subject=agent, intention_id=intention),
        _record(
            two[0],
            0.05,
            kind="intention",
            execution=f"intention:{intention}",
            subject="intention",
            intention_id=intention,
        ),
    )

    rows = await _read(lambda s: reports.report(s, "agents", month=MONTH))
    [mine] = [r for r in rows if r["agent"] == agent]
    assert (mine["runs"], mine["cost_not_known"]) == (12, 1)
    # 0.01 … 0.10 and 0.20; the unknown one left out, never read as 0.
    assert mine["p50_usd"] == pytest.approx(0.06)
    assert mine["p90_usd"] == pytest.approx(0.1)
    assert mine["avg_usd"] == pytest.approx(0.75 / 11, abs=1e-6)

    months = await _read(lambda s: reports.report(s, "intentions", month=MONTH))
    [january] = months
    assert january["intentions"] == 1
    assert january["p95_usd"] == pytest.approx(0.25)


async def test_a_plan_s_margin_at_its_list_and_its_promotional_price(
    two: list[uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        reports,
        "settings",
        SimpleNamespace(
            credit_usd=0.01,
            plan_prices_usd={"growth": 100.0},
            plan_promo_prices_usd={"growth": 50.0},
        ),
    )
    with workspace_scope(two[0]):
        async with session_factory() as session:
            session.add(
                WorkspacePlan(
                    workspace_id=two[0],
                    id=uuid.uuid4(),
                    plan="growth",
                    reason="report",
                    set_by="tests",
                    at=START,
                )
            )
            await session.commit()
    await _keep(two[0], _record(two[0], 20.0), _record(two[0], 10.0))
    # Before its plan, B is on Free: its own row, no price, no margin.
    await _keep(two[1], _record(two[1], 1.5))

    rows = {r["plan"]: r for r in await _read(lambda s: reports.plans(s, month=MONTH))}
    growth = rows["growth"]
    assert (growth["workspaces"], growth["leka_cost_usd"], growth["credits_used"]) == (
        1,
        30.0,
        3000.0,
    )
    assert (growth["list_revenue_usd"], growth["list_margin"]) == (100.0, 0.7)
    assert (growth["promo_revenue_usd"], growth["promo_margin"]) == (50.0, 0.4)
    free = rows["free"]
    assert (free["list_revenue_usd"], free["list_margin"]) == (None, None)


async def test_what_was_wasted_by_purpose_and_two_periods_compared(
    two: list[uuid.UUID],
) -> None:
    purpose = f"agent:waste-{uuid.uuid4().hex[:8]}"
    steps = {
        purpose: {
            "calls": 4,
            "failed": 0,
            "invalid": 1,
            "retries": 1,
            "tokens_in": 4000,
            "tokens_out": 800,
            "cost_usd": 0.4,
            "unpriced": 0,
            "invalid_cost_usd": 0.1,
            "retry_cost_usd": 0.1,
        }
    }
    subject = purpose.removeprefix("agent:")
    await _keep(
        two[0],
        _record(two[0], 0.4, subject=subject, steps=steps, calls=4, retries=1, invalid_calls=1),
        _record(two[0], 0.1, subject=subject, started_at=START + timedelta(days=20)),
    )

    waste = await _read(lambda s: reports.report(s, "waste", month=MONTH))
    [mine] = [r for r in waste if r["purpose"] == purpose]
    assert (mine["invalid_cost_usd"], mine["retry_cost_usd"]) == (0.1, 0.1)
    assert mine["wasted_share"] == pytest.approx(0.5)

    compared = await _read(
        lambda s: reports.compare(
            s,
            (date(2020, 1, 1), date(2020, 1, 15)),
            (date(2020, 1, 15), date(2020, 2, 1)),
        )
    )
    [side] = [r for r in compared if r["subject"] == subject]
    assert (side["avg_cost_usd_before"], side["avg_cost_usd_after"]) == (0.4, 0.1)
    assert side["avg_cost_usd_change"] == pytest.approx(-0.75)
    assert side["retry_rate_before"] == pytest.approx(0.25)


async def test_the_command_writes_a_report_as_csv(
    two: list[uuid.UUID], capsys: pytest.CaptureFixture[str]
) -> None:
    agent = f"agent-{uuid.uuid4().hex[:8]}"
    await _keep(two[0], _record(two[0], 0.3, subject=agent))
    assert await cli._report("agents", "2020-01", "csv") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("month,agent,runs")
    assert any(line.startswith(f"2020-01-01,{agent},1,") for line in out)

    assert await cli._workspaces() == 0
    assert str(two[0]) in capsys.readouterr().out
