"""Usage and cost metering (LEKA-430), against the database.

What these protect: every list price LEKA routes by has its rate in the
database, and a rate is never rewritten; the ledger's row of an execution
says what its calls took and cost — tokens measured, partly or not at all,
a cost estimated, partly or unknown, never 0 for what is not known — and
what LEKA does not measure said so; metered twice, the same row, never two;
one workspace's calls never in another's row; an intention's cost is every
execution done for it — its reading, its analysis, the agent it ran with
both of its calls, every try — by step; the sweep meters what a call was
made for, or a run ended, since its window, and only that.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from leka.capabilities import AgentRun, LLMRun, ModelCall, ModelRate
from leka.capabilities.gateway.profiles import PROFILES
from leka.db import session_factory, system_scope, workspace_scope
from leka.intentions import Intention
from leka.metering import Metering, UsageRecord, execution_of, sweep
from leka.metering.cli import main
from leka.platform import Workspace

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


async def _workspace(name: str) -> uuid.UUID:
    with system_scope():
        async with session_factory() as session:
            found = Workspace(name=name, slug=f"metering-{uuid.uuid4().hex[:10]}")
            session.add(found)
            await session.commit()
            return found.id


async def _drop(workspace_id: uuid.UUID) -> None:
    with system_scope():
        async with session_factory() as session:
            leftover = await session.get(Workspace, workspace_id)
            if leftover is not None:
                await session.delete(leftover)
            await session.commit()


@pytest.fixture
async def workspace() -> AsyncIterator[uuid.UUID]:
    workspace_id = await _workspace("Metering")
    yield workspace_id
    await _drop(workspace_id)


@pytest.fixture
async def other() -> AsyncIterator[uuid.UUID]:
    workspace_id = await _workspace("Elsewhere")
    yield workspace_id
    await _drop(workspace_id)


def _call(workspace_id: uuid.UUID, **fields: Any) -> ModelCall:
    base: dict[str, Any] = {
        "workspace_id": workspace_id,
        "id": uuid.uuid4(),
        "purpose": "agent:application-architecture",
        "tier": "deep",
        "provider": "google",
        "model": "gemini-3.8-flash",
        "version": "gemini-3.8-flash-001",
        "route": "default",
        "attempt": 1,
        "owner": "leka",
        "status": "ok",
        "tokens_in": 1000,
        "tokens_out": 200,
        "tokens_thinking": 0,
        "tokens_cached": 0,
        "tool_calls": 0,
        "usage_reported": True,
        "cost_usd": 0.0015,
        "latency_ms": 800,
        "at": NOW - timedelta(minutes=30),
    }
    return ModelCall(**{**base, **fields})


def _agent_run(workspace_id: uuid.UUID, **fields: Any) -> AgentRun:
    base: dict[str, Any] = {
        "workspace_id": workspace_id,
        "id": uuid.uuid4(),
        "key": "application-architecture",
        "version": "1.2.0",
        "status": "succeeded",
        "format": "markdown",
        "queued_at": NOW - timedelta(minutes=32),
        "started_at": NOW - timedelta(minutes=31),
        "finished_at": NOW - timedelta(minutes=29),
    }
    return AgentRun(**{**base, **fields})


async def _keep(workspace_id: uuid.UUID, *rows: Any) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            for row in rows:
                session.add(row)
                await session.flush()
            await session.commit()


async def _meter(workspace_id: uuid.UUID, *executions: str) -> int:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            count = await Metering(session).meter(workspace_id, executions, now=NOW)
            await session.commit()
            return count


async def _records(workspace_id: uuid.UUID) -> dict[str, UsageRecord]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.scalars(
                select(UsageRecord).where(UsageRecord.workspace_id == workspace_id)
            )
            return {r.execution: r for r in rows}


# ── the rates ───────────────────────────────────────────────────────────────


async def test_every_list_price_has_its_rate_in_the_database() -> None:
    with system_scope():
        async with session_factory() as session:
            rates = {
                (r.provider, r.model, r.since): (
                    r.per_million_in,
                    r.per_million_out,
                    r.per_million_cached,
                )
                for r in (await session.scalars(select(ModelRate))).all()
            }
    for profile in PROFILES:
        for price in profile.prices:
            assert rates[(profile.provider, profile.model, price.since)] == (
                price.per_million_in,
                price.per_million_out,
                price.per_million_cached,
            ), f"{profile.model} from {price.since}: add its rate (a migration, or the command)"


async def test_a_rate_is_never_rewritten() -> None:
    with system_scope():
        async with session_factory() as session:
            with pytest.raises(DBAPIError, match="never rewritten"):
                await session.execute(
                    text(
                        "UPDATE model_rates SET per_million_in = 0 WHERE model = 'gemini-3.8-flash'"
                    )
                )


async def test_a_negative_price_is_refused_by_the_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["rates", "add", "google", "gemini-x", "2027-01-01", "-1", "2"]) == 1
    assert "never negative" in capsys.readouterr().err


# ── an execution's row ──────────────────────────────────────────────────────


def test_a_call_belongs_to_what_its_ref_says_else_its_run_else_its_day() -> None:
    run, at = uuid.uuid4(), datetime(2026, 10, 16, 9, tzinfo=UTC)
    agent = uuid.uuid4()
    assert execution_of(f"agent_run:{agent}", run, "agent:x", at) == f"agent_run:{agent}"
    assert execution_of("company-model", run, "x", at) == f"llm_run:{run}"
    assert execution_of("agent_run:not-an-id", None, "agent:x:deck", at) == (
        "work:agent:x:deck:2026-10-16"
    )


async def test_an_agent_run_is_metered_with_both_its_calls_every_try_and_what_is_not_known(
    workspace: uuid.UUID,
) -> None:
    run = _agent_run(workspace)
    ref = f"agent_run:{run.id}"
    await _keep(
        workspace,
        run,
        # The analysis: not what was asked, then again.
        _call(workspace, ref=ref, status="invalid", cost_usd=0.002, tokens_in=1200),
        _call(workspace, ref=ref, attempt=2, cost_usd=0.003, tool_calls=2),
        # The deck: one try failed, the fallback's provider said no usage.
        _call(
            workspace,
            ref=ref,
            purpose="agent:application-architecture:deck",
            status="failed",
            tokens_in=0,
            tokens_out=0,
            usage_reported=False,
            cost_usd=None,
        ),
        _call(
            workspace,
            ref=ref,
            purpose="agent:application-architecture:deck",
            provider="mistral",
            model="mistral-large-latest",
            route="fallback",
            tokens_in=0,
            tokens_out=0,
            usage_reported=False,
            cost_usd=None,
        ),
    )

    assert await _meter(workspace, ref) == 1

    row = (await _records(workspace))[ref]
    assert (row.kind, row.subject, row.subject_version, row.outcome) == (
        "agent_run",
        "application-architecture",
        "1.2.0",
        "succeeded",
    )
    assert (row.calls, row.failed_calls, row.invalid_calls, row.retries, row.fallbacks) == (
        4,
        1,
        1,
        1,
        1,
    )
    assert (row.tool_calls, row.unreported_calls) == (2, 1)
    # Measured for two answers of three: partial, never short and complete.
    assert (row.tokens_in, row.tokens_out, row.tokens_status) == (2200, 400, "partial")
    assert row.llm_cost_usd == pytest.approx(0.005)
    assert row.leka_cost_usd == pytest.approx(0.005)
    assert row.workspace_cost_usd is None
    assert row.cost_status == "partial"
    assert (row.embedding_cost, row.tool_cost, row.infra_cost) == (
        "not_applicable",
        "unavailable",
        "unavailable",
    )
    assert row.duration_ms == 120_000
    assert row.models == ["google/gemini-3.8-flash", "mistral/mistral-large-latest"]
    steps: dict[str, Any] = row.steps
    analysis = steps["agent:application-architecture"]
    assert analysis["invalid_cost_usd"] == pytest.approx(0.002)
    assert analysis["retry_cost_usd"] == pytest.approx(0.003)
    assert steps["agent:application-architecture:deck"]["unpriced"] == 1


async def test_metered_twice_the_same_row_never_two(workspace: uuid.UUID) -> None:
    run = _agent_run(workspace)
    ref = f"agent_run:{run.id}"
    await _keep(workspace, run, _call(workspace, ref=ref))
    await _meter(workspace, ref)
    first = (await _records(workspace))[ref]

    await _meter(workspace, ref)
    await _meter(workspace, ref)

    records = await _records(workspace)
    assert list(records) == [ref]
    again = records[ref]
    assert (again.id, again.calls, again.llm_cost_usd) == (first.id, 1, first.llm_cost_usd)


async def test_an_execution_without_any_known_usage_says_unknown_not_zero(
    workspace: uuid.UUID,
) -> None:
    run = _agent_run(workspace)
    ref = f"agent_run:{run.id}"
    await _keep(
        workspace,
        run,
        _call(workspace, ref=ref, tokens_in=0, tokens_out=0, usage_reported=False, cost_usd=None),
    )
    await _meter(workspace, ref)

    row = (await _records(workspace))[ref]
    assert (row.tokens_in, row.tokens_status) == (None, "unknown")
    assert (row.llm_cost_usd, row.cost_status) == (None, "unknown")


async def test_one_workspace_s_calls_are_never_in_another_s_row(
    workspace: uuid.UUID, other: uuid.UUID
) -> None:
    run = _agent_run(workspace)
    ref = f"agent_run:{run.id}"
    await _keep(workspace, run, _call(workspace, ref=ref))
    # The same ref, elsewhere: forged or not, not this workspace's.
    await _keep(other, _call(other, ref=ref, cost_usd=9.0))

    await _meter(workspace, ref)

    row = (await _records(workspace))[ref]
    assert row.calls == 1
    assert row.llm_cost_usd == pytest.approx(0.0015)


# ── an intention, end to end ────────────────────────────────────────────────


async def test_an_intention_costs_its_reading_its_analysis_and_the_agents_it_ran(
    workspace: uuid.UUID,
) -> None:
    reading = uuid.uuid4()
    intention = Intention(
        workspace_id=workspace,
        id=uuid.uuid4(),
        text="Why is payment-api slow?",
        title="Why is payment-api slow?",
        status="submitted",
        status_changed_at=NOW,
        understanding={"read_by": {"method": "model", "run_id": str(reading)}},
    )
    run = _agent_run(workspace, intention_id=intention.id)
    agent = f"agent_run:{run.id}"
    await _keep(
        workspace,
        intention,
        LLMRun(
            workspace_id=workspace,
            id=reading,
            purpose="intention.understanding",
            status="succeeded",
            started_at=NOW - timedelta(minutes=40),
            finished_at=NOW - timedelta(minutes=40),
        ),
        _call(workspace, purpose="intention.understanding", run_id=reading, cost_usd=0.0002),
        _call(
            workspace,
            purpose="capability.synthesis",
            ref=f"intention:{intention.id}",
            cost_usd=0.001,
        ),
        run,
        _call(workspace, ref=agent, cost_usd=0.003),
        _call(workspace, ref=agent, purpose="agent:application-architecture:deck", cost_usd=0.004),
        # Another intention's: not this one's.
        _call(workspace, ref=f"intention:{uuid.uuid4()}", cost_usd=1.0),
    )

    with workspace_scope(workspace):
        async with session_factory() as session:
            cost = await Metering(session).intention_cost(workspace, intention.id, now=NOW)
            await session.commit()

    assert sorted(e.kind for e in cost.executions) == ["agent_run", "intention", "llm_run"]
    assert cost.calls == 4
    assert cost.llm_cost_usd == pytest.approx(0.0082)
    assert (cost.tokens_in, cost.tokens_status, cost.cost_status) == (4000, "measured", "estimated")
    assert {k: round(v.cost_usd, 6) for k, v in cost.steps.items()} == {
        "intention.understanding": 0.0002,
        "capability.synthesis": 0.001,
        "agent:application-architecture": 0.003,
        "agent:application-architecture:deck": 0.004,
    }
    assert cost.embedding_cost == "not_applicable"


# ── the sweep ───────────────────────────────────────────────────────────────


async def test_the_sweep_meters_what_was_done_since_its_window_and_only_that(
    workspace: uuid.UUID,
) -> None:
    recent, ended, old = _agent_run(workspace), _agent_run(workspace), _agent_run(workspace)
    # Ended without asking a model: metered all the same, nothing to count.
    ended.status, ended.finished_at = "failed", NOW - timedelta(minutes=5)
    old.started_at, old.finished_at = NOW - timedelta(days=3), NOW - timedelta(days=3)
    await _keep(
        workspace,
        recent,
        ended,
        old,
        _call(workspace, ref=f"agent_run:{recent.id}"),
        _call(workspace, ref=f"agent_run:{old.id}", at=NOW - timedelta(days=3)),
    )

    metered = await sweep(since=NOW - timedelta(hours=1), now=NOW)

    assert metered[str(workspace)] == 2
    records = await _records(workspace)
    assert set(records) == {f"agent_run:{recent.id}", f"agent_run:{ended.id}"}
    nothing = records[f"agent_run:{ended.id}"]
    assert (nothing.outcome, nothing.calls, nothing.tokens_status, nothing.cost_status) == (
        "failed",
        0,
        "none",
        "none",
    )
    assert nothing.llm_cost_usd is None
