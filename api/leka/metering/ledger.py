"""A workspace's AI credits, line by line (LEKA-553): its ledger, kept level
with what LEKA knows, and reconciled with what its work consumed.

    post()             the lines LEKA knows of and has not written yet:
                       each month's credits given by its plan (a plan
                       changed in the month, the difference), each pack,
                       each execution metered (metered again, the
                       difference), each month closed — what was left of it
    run_ledger_sweep() every workspace, every hour after the metering sweep:
                       the executions metered lately; a workspace with no
                       line yet, its whole history
    month()            one month read from its lines, set beside the source:
                       what LEKA's models cost it, as the gateway counts it

Every line is written once: its `reference` says the operation it records,
unique in the workspace — a sweep run twice, or two at once, writes nothing
twice. A line is never changed: a cost metered again, or a plan changed, is
a line of its own for the difference. A month's balance is the sum of its
lines.

Consumption is what the metering ledger (`usage_records`) says LEKA's
models cost each execution, in credits: an execution LEKA could not price
writes no line — a cost is never invented — and is counted apart. What the
gateway counted and the metering sweep has not yet (the last minutes) is
said pending, never guessed.

A month closes two days after it ends, once the metering sweeps caught up:
what was left of it expires — credits never carry over (leka.governance.plans).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import ModelCall
from leka.db import session_factory, system_scope
from leka.governance import (
    CreditPack,
    CreditTransaction,
    allowance,
    credits_of,
    month_of,
    next_month,
    plan_at,
    plan_of,
)
from leka.metering.models import UsageRecord
from leka.platform import Workspace

logger = structlog.get_logger(__name__)

# How long after a month ends it closes: the metering sweeps have caught up.
SETTLE = timedelta(days=2)
# The executions a sweep reads again: the metering sweep meters again those
# of the last hours.
RECENT = timedelta(hours=6)
# A difference smaller than this is rounding.
EPSILON = 0.0001


def _start(period: date) -> datetime:
    return datetime.combine(period, time.min, tzinfo=UTC)


def label(period: date) -> str:
    return period.strftime("%Y-%m")


@dataclass
class Posted:
    grants: int = 0
    packs: int = 0
    consumptions: int = 0
    expirations: int = 0

    @property
    def total(self) -> int:
        return self.grants + self.packs + self.consumptions + self.expirations


async def _write(session: AsyncSession, workspace_id: uuid.UUID, **line: Any) -> bool:
    """One line, unless its reference was written already: True, written."""
    written = await session.scalar(
        insert(CreditTransaction)
        .values(workspace_id=workspace_id, id=uuid.uuid4(), **line)
        .on_conflict_do_nothing(constraint="uq_credit_transactions_reference")
        .returning(CreditTransaction.id)
    )
    return written is not None


async def _numbered(session: AsyncSession, workspace_id: uuid.UUID, prefix: str) -> str:
    """The next reference of an operation written again: prefix:1, prefix:2…"""
    count = await session.scalar(
        select(func.count()).where(
            CreditTransaction.workspace_id == workspace_id,
            CreditTransaction.reference.startswith(f"{prefix}:", autoescape=True),
        )
    )
    return f"{prefix}:{int(count or 0) + 1}"


async def post(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    now: datetime,
    metered_since: datetime | None = None,
) -> Posted:
    """Its ledger brought level with what LEKA knows: the grants of every
    month since it was created, its packs, the executions metered (since
    `metered_since`; none, all of them), the months closed. Returns what
    was written."""
    posted = Posted()
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return posted
    current = month_of(now)

    # Each month's credits, by the plan in force — the month's latest, as
    # the allowance counts it.
    granted = dict(
        (
            await session.execute(
                select(CreditTransaction.period, func.sum(CreditTransaction.credits))
                .where(
                    CreditTransaction.workspace_id == workspace_id,
                    CreditTransaction.kind == "grant",
                    CreditTransaction.origin == "plan",
                )
                .group_by(CreditTransaction.period)
            )
        )
        .tuples()
        .all()
    )
    period = month_of(workspace.created_at)
    while period <= current:
        plan = (
            await plan_of(session, workspace_id)
            if period == current
            else await plan_at(session, workspace_id, _start(next_month(period)))
        )
        before = float(granted.get(period) or 0.0)
        delta = plan.monthly_credits - before
        if abs(delta) >= EPSILON:
            first = period not in granted
            if await _write(
                session,
                workspace_id,
                kind="grant",
                credits=delta,
                period=period,
                at=max(_start(period), workspace.created_at) if first else now,
                origin="plan",
                reference=await _numbered(session, workspace_id, f"plan:{label(period)}"),
                detail={"plan": plan.name, "monthly": plan.monthly_credits},
            ):
                posted.grants += 1
        period = next_month(period)

    # Each pack, as given.
    written = set(
        (
            await session.scalars(
                select(CreditTransaction.reference).where(
                    CreditTransaction.workspace_id == workspace_id,
                    CreditTransaction.origin == "pack",
                )
            )
        ).all()
    )
    for pack in (
        await session.scalars(
            select(CreditPack)
            .where(CreditPack.workspace_id == workspace_id)
            .order_by(CreditPack.at)
        )
    ).all():
        if f"pack:{pack.id}" in written:
            continue
        if await _write(
            session,
            workspace_id,
            kind="grant",
            credits=float(pack.credits),
            period=pack.period,
            at=pack.at,
            origin="pack",
            reference=f"pack:{pack.id}",
            by_whom=pack.granted_by,
            reason=pack.reason,
            detail={"pack_id": str(pack.id)},
        ):
            posted.packs += 1

    # Each execution priced by the metering ledger: what it consumed; metered
    # again, the difference.
    metered = select(UsageRecord).where(
        UsageRecord.workspace_id == workspace_id, UsageRecord.leka_cost_usd.is_not(None)
    )
    if metered_since is not None:
        metered = metered.where(UsageRecord.metered_at >= metered_since)
    records = (await session.scalars(metered)).all()
    if records:
        consumed = dict(
            (
                await session.execute(
                    select(CreditTransaction.execution, func.sum(CreditTransaction.credits))
                    .where(
                        CreditTransaction.workspace_id == workspace_id,
                        CreditTransaction.kind == "consumption",
                        CreditTransaction.execution.in_([r.execution for r in records]),
                    )
                    .group_by(CreditTransaction.execution)
                )
            )
            .tuples()
            .all()
        )
        for record in records:
            cost = float(record.leka_cost_usd or 0.0)
            delta = -round(credits_of(cost), 4) - float(consumed.get(record.execution) or 0.0)
            if abs(delta) < EPSILON:
                continue
            if await _write(
                session,
                workspace_id,
                kind="consumption",
                credits=delta,
                period=month_of(record.started_at),
                at=record.started_at if record.execution not in consumed else now,
                origin="metering",
                reference=await _numbered(session, workspace_id, f"use:{record.execution}"),
                execution=record.execution,
                subject=record.subject,
                detail={
                    "cost_usd": cost,
                    "cost_status": record.cost_status,
                    "kind": record.kind,
                    "models": list(record.models),
                },
            ):
                posted.consumptions += 1

    # Each month closed: what was left of it, expired.
    closed = set(
        (
            await session.scalars(
                select(CreditTransaction.period).where(
                    CreditTransaction.workspace_id == workspace_id,
                    CreditTransaction.kind == "expiration",
                )
            )
        ).all()
    )
    balances = dict(
        (
            await session.execute(
                select(CreditTransaction.period, func.sum(CreditTransaction.credits))
                .where(CreditTransaction.workspace_id == workspace_id)
                .group_by(CreditTransaction.period)
            )
        )
        .tuples()
        .all()
    )
    for period, balance in sorted(balances.items()):
        ends = _start(next_month(period))
        if period in closed or ends + SETTLE > now:
            continue
        left = round(float(balance or 0.0), 4)
        # Overspent: nothing expires, the month stays below 0 as it was.
        if await _write(
            session,
            workspace_id,
            kind="expiration",
            credits=-left if left > 0 else 0.0,
            period=period,
            at=ends,
            origin="close",
            reference=f"expire:{label(period)}",
            detail={"left": left},
        ):
            posted.expirations += 1
    return posted


def run_ledger_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(sweep_ledger())


async def sweep_ledger(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace's ledger brought level: the executions metered in the
    last hours; a workspace with no line yet, its whole history. Each in a
    transaction of its own: one that fails is logged, the others go on."""
    moment = now or datetime.now(UTC)
    with system_scope():
        async with session_factory() as session:
            workspaces = (await session.scalars(select(Workspace.id))).all()
            started = set(
                (await session.scalars(select(CreditTransaction.workspace_id).distinct())).all()
            )
    written: dict[str, int] = {}
    for workspace_id in workspaces:
        try:
            with system_scope():
                async with session_factory() as session:
                    posted = await post(
                        session,
                        workspace_id,
                        now=moment,
                        metered_since=moment - RECENT if workspace_id in started else None,
                    )
                    await session.commit()
        except Exception:
            logger.exception("credit_ledger_failed", workspace=str(workspace_id))
            continue
        if posted.total:
            written[str(workspace_id)] = posted.total
    if written:
        logger.info("credit_ledger_posted", workspaces=len(written), lines=sum(written.values()))
    return written


# ── A month, reconciled ──────────────────────────────────────────────────────


@dataclass
class Month:
    """One month of a workspace's credits, from its ledger, beside what the
    gateway counted. Credits are positive here: given, consumed, expired."""

    period: date
    granted: float = 0.0
    packs: float = 0.0
    refunds: float = 0.0
    adjustments: float = 0.0
    consumed: float = 0.0
    expired: float = 0.0
    lines: int = 0
    # What LEKA's models cost it that month, in credits, as the gateway
    # counts it (the source the ledger's consumption is metered from).
    source: float = 0.0
    # Executions whose cost LEKA could not price: no line, never a guess.
    unpriced: int = 0
    # The allowance the gateway counts this month, now (none: a month past).
    allowance_now: int | None = None
    closed: bool = False
    by_subject: dict[str, float] = field(default_factory=dict)

    @property
    def balance(self) -> float:
        given = self.granted + self.packs + self.refunds + self.adjustments
        return round(given - self.consumed - self.expired, 4)

    @property
    def pending(self) -> float:
        """Consumed at the gateway, not yet in the ledger (metering to come)."""
        return round(self.source - self.consumed, 4)

    @property
    def allowance_gap(self) -> float | None:
        """The month's allowance the ledger gives, beside the gateway's."""
        if self.allowance_now is None:
            return None
        given = self.granted + self.packs + self.refunds + self.adjustments
        return round(self.allowance_now - given, 4)


async def month(
    session: AsyncSession, workspace_id: uuid.UUID, period: date, *, now: datetime
) -> Month:
    found = Month(period=period, closed=_start(next_month(period)) + SETTLE <= now)
    for kind, origin, total, count in (
        await session.execute(
            select(
                CreditTransaction.kind,
                CreditTransaction.origin,
                func.sum(CreditTransaction.credits),
                func.count(),
            )
            .where(
                CreditTransaction.workspace_id == workspace_id,
                CreditTransaction.period == period,
            )
            .group_by(CreditTransaction.kind, CreditTransaction.origin)
        )
    ).tuples():
        value = float(total or 0.0)
        found.lines += int(count)
        if kind == "grant":
            if origin == "pack":
                found.packs += value
            else:
                found.granted += value
        elif kind == "consumption":
            found.consumed -= value
        elif kind == "expiration":
            found.expired -= value
        elif kind == "refund":
            found.refunds += value
        else:
            found.adjustments += value
    for subject, total in (
        await session.execute(
            select(CreditTransaction.subject, func.sum(CreditTransaction.credits))
            .where(
                CreditTransaction.workspace_id == workspace_id,
                CreditTransaction.period == period,
                CreditTransaction.kind == "consumption",
            )
            .group_by(CreditTransaction.subject)
        )
    ).tuples():
        found.by_subject[subject or ""] = round(-float(total or 0.0), 4)
    start, end = _start(period), _start(next_month(period))
    spent = await session.scalar(
        select(func.coalesce(func.sum(ModelCall.cost_usd), 0.0)).where(
            ModelCall.workspace_id == workspace_id,
            ModelCall.at >= start,
            ModelCall.at < end,
            ModelCall.owner == "leka",
            ModelCall.status != "failed",
        )
    )
    found.source = round(credits_of(float(spent or 0.0)), 4)
    found.unpriced = int(
        await session.scalar(
            select(func.count()).where(
                UsageRecord.workspace_id == workspace_id,
                UsageRecord.started_at >= start,
                UsageRecord.started_at < end,
                UsageRecord.calls > 0,
                UsageRecord.cost_status.in_(("unknown", "partial")),
            )
        )
        or 0
    )
    if period == month_of(now):
        found.allowance_now = (await allowance(session, workspace_id, now)).credits
    return found


__all__ = ["Month", "Posted", "label", "month", "post", "run_ledger_sweep", "sweep_ledger"]
