"""A workspace's plan and its AI credits (LEKA-430).

    plan_of()      its plan now — the latest it was put on; none, Free
    allowance()    its credits for a month: the plan's, and the packs added
    set_plan()     a plan from now on — by LEKA, said why, kept, audited
    add_pack()     credits added to this month — the same

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
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core.config import settings
from leka.core.settings.credits import PLANS
from leka.governance.audit import Target, audit
from leka.governance.models import CreditPack, WorkspacePlan

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

    @property
    def credits(self) -> int:
        return self.plan.monthly_credits + self.packs


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
    return Allowance(await plan_of(session, workspace_id), period, int(packs or 0))


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
