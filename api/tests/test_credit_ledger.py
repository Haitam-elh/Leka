"""The AI credits' ledger (LEKA-553): every movement of a workspace's
credits written once — each month's grant by its plan, each pack, each
execution metered, each month closed — never changed; a month's balance
the sum of its lines, reconciled with what LEKA's models cost it at the
gateway; what LEKA's team gives back or adjusts, counted in the allowance
at once.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from leka.capabilities import ModelCall
from leka.core.config import settings
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import (
    AuditEvent,
    CreditPack,
    CreditTransaction,
    PlanError,
    WorkspacePlan,
    adjust,
    allowance,
)
from leka.metering import UsageRecord, credits_now, ledger_month, post_ledger, sweep_ledger
from leka.platform import Workspace

pytestmark = pytest.mark.integration

# Two days past a month's end, so the month before closes.
NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
OCTOBER = date(2026, 10, 1)
NOVEMBER = date(2026, 11, 1)


def _c(cost_usd: float) -> float:
    return round(cost_usd / settings.credit_usd, 4)


def _usage(
    workspace_id: uuid.UUID, execution: str, at: datetime, cost: float | None
) -> UsageRecord:
    return UsageRecord(
        workspace_id=workspace_id,
        execution=execution,
        kind="agent_run",
        subject="code-review",
        outcome="succeeded",
        started_at=at,
        calls=2,
        failed_calls=0,
        invalid_calls=0,
        retries=0,
        fallbacks=0,
        tool_calls=0,
        unreported_calls=0,
        latency_ms=0,
        tokens_status="measured",
        cost_status="estimated" if cost is not None else "unknown",
        embedding_cost="not_applicable",
        tool_cost="not_applicable",
        infra_cost="not_applicable",
        leka_cost_usd=cost,
        llm_cost_usd=cost,
        models=["google/gemini-2.5-pro"],
        metered_at=at,
    )


def _call(workspace_id: uuid.UUID, at: datetime, cost: float) -> ModelCall:
    return ModelCall(
        workspace_id=workspace_id,
        purpose="agent:code-review",
        tier="deep",
        provider="google",
        model="gemini-2.5-pro",
        route="default",
        owner="leka",
        status="ok",
        cost_usd=cost,
        at=at,
    )


async def _world() -> uuid.UUID:
    """A workspace since September: on Growth from its first day, on
    Business from 10 November; a pack in November; four executions, one
    LEKA could not price; the gateway's calls, one not metered yet."""
    marker = uuid.uuid4().hex[:8]
    workspace = Workspace(
        id=uuid.uuid4(),
        name=f"Ledger {marker}",
        slug=f"ledger-{marker}",
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    wid = workspace.id
    with system_scope():
        async with session_factory() as session:
            session.add(workspace)
            await session.flush()
            session.add_all(
                [
                    WorkspacePlan(
                        workspace_id=wid,
                        plan="growth",
                        reason="test",
                        set_by="test",
                        at=datetime(2026, 9, 15, tzinfo=UTC),
                    ),
                    WorkspacePlan(
                        workspace_id=wid,
                        plan="business",
                        reason="upgrade",
                        set_by="test",
                        at=datetime(2026, 11, 10, tzinfo=UTC),
                    ),
                    CreditPack(
                        workspace_id=wid,
                        credits=500,
                        period=NOVEMBER,
                        reason="a commercial gesture",
                        granted_by="ops",
                        at=datetime(2026, 11, 12, tzinfo=UTC),
                    ),
                    _usage(wid, "agent_run:a", datetime(2026, 10, 3, tzinfo=UTC), 2.0),
                    _usage(wid, "agent_run:b", datetime(2026, 10, 20, tzinfo=UTC), 1.0),
                    _usage(wid, "agent_run:c", datetime(2026, 11, 14, tzinfo=UTC), 3.0),
                    _usage(wid, "agent_run:d", datetime(2026, 11, 15, tzinfo=UTC), None),
                    _call(wid, datetime(2026, 11, 14, tzinfo=UTC), 3.0),
                    # Not metered yet.
                    _call(wid, datetime(2026, 11, 20, 11, tzinfo=UTC), 0.5),
                ]
            )
            await session.commit()
    return wid


async def _post(wid: uuid.UUID, **said: Any) -> Any:
    with system_scope():
        async with session_factory() as session:
            posted = await post_ledger(session, wid, now=said.pop("now", NOW), **said)
            await session.commit()
            return posted


async def _lines(wid: uuid.UUID) -> list[CreditTransaction]:
    with system_scope():
        async with session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(CreditTransaction)
                        .where(CreditTransaction.workspace_id == wid)
                        .order_by(CreditTransaction.at, CreditTransaction.reference)
                    )
                ).all()
            )


async def _month(wid: uuid.UUID, period: date) -> Any:
    with system_scope():
        async with session_factory() as session:
            return await ledger_month(session, wid, period, now=NOW)


async def test_each_movement_is_written_once_and_a_closed_month_balances() -> None:
    wid = await _world()
    posted = await _post(wid)
    growth, business = settings.plan_credits["growth"], settings.plan_credits["business"]
    # September, October, November: the plan's; the pack; three executions
    # priced; September and October closed.
    assert (posted.grants, posted.packs, posted.consumptions, posted.expirations) == (3, 1, 3, 2)
    lines = await _lines(wid)
    references = {line.reference: line for line in lines}
    assert float(references["plan:2026-11:1"].credits) == business
    assert references["plan:2026-11:1"].detail["plan"] == "business"
    # October's plan was the one in force when it ended: Growth.
    assert float(references["plan:2026-10:1"].credits) == growth
    pack = next(line for line in lines if line.origin == "pack")
    assert (float(pack.credits), pack.by_whom, pack.reason) == (500, "ops", "a commercial gesture")
    assert float(references["use:agent_run:a:1"].credits) == -_c(2.0)
    assert references["use:agent_run:a:1"].period == OCTOBER
    # Never a cost invented: the execution LEKA could not price writes nothing.
    assert not any(line.execution == "agent_run:d" for line in lines)
    assert float(references["expire:2026-10"].credits) == -(growth - _c(3.0))

    # Run again, nothing more: every line is written once.
    again = await _post(wid)
    assert again.total == 0
    assert len(await _lines(wid)) == len(lines)

    october = await _month(wid, OCTOBER)
    assert (october.granted, october.consumed, october.expired) == (
        growth,
        _c(3.0),
        growth - _c(3.0),
    )
    assert (october.balance, october.closed) == (0.0, True)


async def test_a_cost_metered_again_or_a_plan_changed_is_a_line_for_the_difference() -> None:
    wid = await _world()
    await _post(wid)
    with system_scope():
        async with session_factory() as session:
            # Metered again once the run ended: dearer.
            await session.execute(
                text(
                    "UPDATE usage_records SET leka_cost_usd = 4.5, metered_at = :at"
                    " WHERE workspace_id = :w AND execution = 'agent_run:c'"
                ),
                {"w": wid, "at": NOW},
            )
            # Put back on Growth the same month.
            session.add(
                WorkspacePlan(
                    workspace_id=wid,
                    plan="growth",
                    reason="downgrade",
                    set_by="test",
                    at=NOW - timedelta(hours=1),
                )
            )
            await session.commit()
    posted = await _post(wid, metered_since=NOW - timedelta(hours=6))
    assert (posted.grants, posted.consumptions) == (1, 1)
    references = {line.reference: line for line in await _lines(wid)}
    assert float(references["use:agent_run:c:2"].credits) == -_c(1.5)
    assert float(references["plan:2026-11:2"].credits) == (
        settings.plan_credits["growth"] - settings.plan_credits["business"]
    )
    november = await _month(wid, NOVEMBER)
    assert november.consumed == _c(4.5)
    assert november.granted == settings.plan_credits["growth"]
    # The gateway's allowance and the ledger's, the same.
    assert november.allowance_gap == 0.0


async def test_a_month_is_reconciled_with_the_gateway() -> None:
    wid = await _world()
    await _post(wid)
    november = await _month(wid, NOVEMBER)
    # Consumed at the gateway: 3.5 dollars; in the ledger: the 3 metered.
    assert november.source == _c(3.5)
    assert november.pending == _c(0.5)
    assert november.unpriced == 1
    assert november.allowance_now == settings.plan_credits["business"] + 500
    assert november.allowance_gap == 0.0
    assert november.by_subject == {"code-review": _c(3.0)}
    with workspace_scope(wid):
        async with session_factory() as session:
            live = await credits_now(session, wid, now=NOW)
    # The ledger's balance, less what is pending, is what the gateway leaves.
    assert round(november.balance - november.pending, 2) == live.remaining


async def test_what_leka_s_team_adjusts_counts_at_once_and_is_written_once() -> None:
    wid = await _world()
    with workspace_scope(wid):
        async with session_factory() as session:
            before = (await allowance(session, wid, NOW)).credits
            line, written = await adjust(
                session,
                wid,
                "adjustment",
                -300,
                by="LEKA ADMIN ops@leka.test",
                reason="credits given twice by mistake",
                reference="admin:k1",
                at=NOW,
            )
            assert written
            again, written_again = await adjust(
                session,
                wid,
                "adjustment",
                -300,
                by="LEKA ADMIN ops@leka.test",
                reason="credits given twice by mistake",
                reference="admin:k1",
                at=NOW,
            )
            assert (again.id, written_again) == (line.id, False)
            given = await allowance(session, wid, NOW)
            assert (given.adjustments, given.credits) == (-300, before - 300)
            with pytest.raises(PlanError):
                await adjust(
                    session, wid, "refund", -5, by="x", reason="y", reference="admin:k2", at=NOW
                )
            await session.commit()
        async with session_factory() as session:
            trail = (
                await session.scalars(
                    select(AuditEvent.action).where(AuditEvent.workspace_id == wid)
                )
            ).all()
    assert list(trail).count("workspace.credits_adjusted") == 1
    november = await _month(wid, NOVEMBER)
    assert november.adjustments == -300.0


async def test_a_line_is_never_changed_and_goes_with_its_workspace() -> None:
    wid = await _world()
    await _post(wid)
    with system_scope():
        async with session_factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(
                    text("UPDATE credit_transactions SET credits = 0 WHERE workspace_id = :w"),
                    {"w": wid},
                )
            await session.rollback()
        async with session_factory() as session:
            await session.execute(delete(Workspace).where(Workspace.id == wid))
            await session.commit()
    assert await _lines(wid) == []


async def test_the_sweep_posts_a_new_workspace_s_whole_history() -> None:
    wid = await _world()
    written = await sweep_ledger(now=NOW)
    assert written[str(wid)] == 9
    assert (await sweep_ledger(now=NOW)).get(str(wid)) is None
