"""A workspace's plan and its AI credits (LEKA-430).

    plan_of()      its plan now — the latest it was put on; none, Free
    allowance()    its credits for a month: the plan's, the packs added, and
                   what LEKA's team gave back or adjusted (LEKA-553)
    set_plan()     a plan from now on — by LEKA, said why, kept, audited
    add_pack()     credits added to this month — the same
    adjust()       credits given back or adjusted by LEKA's team, a line of
                   the ledger of its own — the same, written once

A credit is worth `settings.credit_usd` of LEKA's model cost: what is spent
is read where the models are called (capabilities); what may be spent, here.
Plans are LEKA's to give — no person of the workspace changes them: the
server command (leka/metering/cli.py) is the only way in, its operator named.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core.config import settings
from leka.core.settings.credits import PLANS
from leka.governance.audit import Target, audit
from leka.governance.models import MANUAL_KINDS, CreditPack, CreditTransaction, WorkspacePlan

FREE = "free"


class PlanError(ValueError):
    """A plan or a pack that cannot be: said why."""


@dataclass(frozen=True)
class Plan:
    name: str
    monthly_credits: int
    since: datetime | None  # none: never set — Free from the start


@dataclass(frozen=True)
class Allowance:
    plan: Plan
    period: date  # the month's first day
    packs: int
    # Given back or adjusted by LEKA's team this month (LEKA-553), whole credits.
    adjustments: int = 0

    @property
    def credits(self) -> int:
        return self.plan.monthly_credits + self.packs + self.adjustments


def month_of(at: datetime) -> date:
    return at.astimezone(UTC).date().replace(day=1)


def next_month(period: date) -> date:
    return (
        period.replace(year=period.year + 1, month=1)
        if period.month == 12
        else (period.replace(month=period.month + 1))
    )


def credits_of(cost_usd: float) -> float:
    """What a cost is, in credits."""
    return cost_usd / settings.credit_usd


def plan_credits(name: str) -> int:
    return int(settings.plan_credits.get(name, 0))


async def plan_of(session: AsyncSession, workspace_id: uuid.UUID) -> Plan:
    row = await session.scalar(
        select(WorkspacePlan)
        .where(WorkspacePlan.workspace_id == workspace_id)
        .order_by(WorkspacePlan.at.desc(), WorkspacePlan.created_at.desc())
        .limit(1)
    )
    if row is None:
        return Plan(FREE, plan_credits(FREE), None)
    monthly = row.monthly_credits if row.monthly_credits is not None else plan_credits(row.plan)
    return Plan(row.plan, monthly, row.at)


async def allowance(session: AsyncSession, workspace_id: uuid.UUID, at: datetime) -> Allowance:
    period = month_of(at)
    packs = await session.scalar(
        select(func.coalesce(func.sum(CreditPack.credits), 0)).where(
            CreditPack.workspace_id == workspace_id, CreditPack.period == period
        )
    )
    adjusted = await session.scalar(
        select(func.coalesce(func.sum(CreditTransaction.credits), 0)).where(
            CreditTransaction.workspace_id == workspace_id,
            CreditTransaction.period == period,
            CreditTransaction.kind.in_(MANUAL_KINDS),
        )
    )
    return Allowance(
        await plan_of(session, workspace_id), period, int(packs or 0), round(float(adjusted or 0))
    )


async def plan_at(session: AsyncSession, workspace_id: uuid.UUID, at: datetime) -> Plan:
    """Its plan at a moment: the latest it was put on before then; none, Free."""
    row = await session.scalar(
        select(WorkspacePlan)
        .where(WorkspacePlan.workspace_id == workspace_id, WorkspacePlan.at < at)
        .order_by(WorkspacePlan.at.desc(), WorkspacePlan.created_at.desc())
        .limit(1)
    )
    if row is None:
        return Plan(FREE, plan_credits(FREE), None)
    monthly = row.monthly_credits if row.monthly_credits is not None else plan_credits(row.plan)
    return Plan(row.plan, monthly, row.at)


async def plans(session: AsyncSession, workspace_id: uuid.UUID) -> list[WorkspacePlan]:
    """Every plan it was put on, the latest first."""
    return list(
        (
            await session.scalars(
                select(WorkspacePlan)
                .where(WorkspacePlan.workspace_id == workspace_id)
                .order_by(WorkspacePlan.at.desc(), WorkspacePlan.created_at.desc())
            )
        ).all()
    )


async def set_plan(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    plan: str,
    *,
    by: str,
    reason: str,
    monthly_credits: int | None = None,
    at: datetime | None = None,
) -> WorkspacePlan:
    if plan not in PLANS:
        msg = f"unknown plan {plan!r}: one of {', '.join(PLANS)}"
        raise PlanError(msg)
    if monthly_credits is not None and monthly_credits < 0:
        raise PlanError("credits are never negative")
    if not reason.strip() or not by.strip():
        raise PlanError("who and why are said")
    before = await plan_of(session, workspace_id)
    row = WorkspacePlan(
        workspace_id=workspace_id,
        id=uuid.uuid4(),
        plan=plan,
        monthly_credits=monthly_credits,
        reason=reason.strip()[:300],
        set_by=by.strip()[:100],
        at=at or datetime.now(UTC),
    )
    session.add(row)
    audit(
        session,
        workspace_id,
        "workspace",
        "workspace.plan_changed",
        target=Target("workspace", workspace_id),
        detail={
            "before": before.name,
            "after": plan,
            "monthly_credits": monthly_credits,
            "by": row.set_by,
            "reason": row.reason,
        },
    )
    await session.flush()
    return row


async def add_pack(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    amount: int,
    *,
    by: str,
    reason: str,
    at: datetime | None = None,
) -> CreditPack:
    if amount <= 0:
        raise PlanError("a pack adds credits")
    if not reason.strip() or not by.strip():
        raise PlanError("who and why are said")
    moment = at or datetime.now(UTC)
    row = CreditPack(
        workspace_id=workspace_id,
        id=uuid.uuid4(),
        credits=amount,
        period=month_of(moment),
        reason=reason.strip()[:300],
        granted_by=by.strip()[:100],
        at=moment,
    )
    session.add(row)
    audit(
        session,
        workspace_id,
        "workspace",
        "workspace.credits_added",
        target=Target("workspace", workspace_id),
        detail={"credits": amount, "period": row.period.isoformat(), "by": row.granted_by},
    )
    await session.flush()
    return row


async def adjust(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    kind: str,
    amount: int,
    *,
    by: str,
    reason: str,
    reference: str,
    at: datetime | None = None,
    detail: dict[str, object] | None = None,
) -> tuple[CreditTransaction, bool]:
    """Credits given back (`refund`, more than 0) or adjusted (`adjustment`,
    added or taken) by LEKA's team in this month (LEKA-553): a line of the
    ledger, counted in the month's allowance at once. Written once per
    `reference`: sent again, the line already written is returned, and
    False. Said who and why, and audited in the workspace's trail."""
    if kind not in MANUAL_KINDS:
        raise PlanError("a refund or an adjustment")
    if amount == 0 or (kind == "refund" and amount < 0):
        raise PlanError("a refund gives credits back; an adjustment adds or takes some")
    if not reason.strip() or not by.strip() or not reference.strip():
        raise PlanError("who, why and the operation are said")
    moment = at or datetime.now(UTC)
    written = await session.scalar(
        insert(CreditTransaction)
        .values(
            workspace_id=workspace_id,
            id=uuid.uuid4(),
            kind=kind,
            credits=float(amount),
            period=month_of(moment),
            at=moment,
            origin="admin",
            reference=reference.strip()[:200],
            by_whom=by.strip()[:320],
            reason=reason.strip()[:300],
            detail=detail or {},
        )
        .on_conflict_do_nothing(constraint="uq_credit_transactions_reference")
        .returning(CreditTransaction.id)
    )
    row = await session.scalar(
        select(CreditTransaction).where(
            CreditTransaction.workspace_id == workspace_id,
            CreditTransaction.reference == reference.strip()[:200],
        )
    )
    if row is None:  # pragma: no cover — written or found, in one transaction
        raise PlanError("the movement could not be written")
    if written is not None:
        audit(
            session,
            workspace_id,
            "workspace",
            "workspace.credits_adjusted",
            target=Target("workspace", workspace_id),
            detail={
                "kind": kind,
                "credits": amount,
                "period": row.period.isoformat(),
                "by": "LEKA",
            },
        )
    return row, written is not None
