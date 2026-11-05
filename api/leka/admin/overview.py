"""The figures of LEKA ADMIN's home (LEKA-544, LEKA-548), over a period.

Each figure is read from real rows, and docs/admin/api.md defines each one.
Demonstration organisations (LEKA-449) are left out of every figure. What
LEKA does not record yet is null, never 0: revenue (MRR, ARR) waits for the
invoices LEKA-554 keeps.

  acquisition  organisations and people, all and new in the period; the
               organisations by plan now
  activity     people active today, in 7 days, in 30 days (seen in the
               product: the journal's user.active); intentions asked,
               completed, failed in the period
  product      agent runs in the period, their success rate, the agents
               used, the organisations that ran one; credits consumed
  business     subscriptions started and cancelled, payments failed in the
               period (Stripe's events); organisations paying now
  technical    sources in error now; syncs and background jobs failed in the
               period
  series       per day (per month past 90 days): people signed up, active,
               intentions asked, credits consumed
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.models import ActivityEvent
from leka.background import JobRun
from leka.billing import BillingAccount
from leka.capabilities import AgentRun
from leka.connectors import HealthStatus, Source, SourceStatus
from leka.core.config import settings
from leka.governance import WorkspacePlan
from leka.identity import User
from leka.metering import UsageRecord
from leka.platform import Workspace

Period = Literal["today", "7d", "30d", "90d", "12m", "custom"]
PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}
# Stripe's statuses that keep a plan paid for, as billing counts them.
PAYING = ("active", "trialing", "past_due")


class AdminWindow(BaseModel):
    period: Period
    start: datetime
    end: datetime
    bucket: Literal["day", "month"]


class AdminAcquisition(BaseModel):
    organisations: int
    organisations_new: int
    users: int
    users_new: int
    by_plan: dict[str, int] = Field(description="Organisations by their plan now.")


class AdminActivity(BaseModel):
    dau: int = Field(description="People seen in the product today (UTC).")
    wau: int = Field(description="…in the last 7 days.")
    mau: int = Field(description="…in the last 30 days.")
    intentions_created: int
    intentions_completed: int
    intentions_failed: int


class AdminProduct(BaseModel):
    agent_runs: int
    agent_success_rate: float | None = Field(
        description="Succeeded out of the runs that ended; null: none."
    )
    agents_used: int
    organisations_running_agents: int
    credits_consumed: float | None = Field(description="Null: no cost LEKA could measure.")


class AdminBusiness(BaseModel):
    subscriptions_started: int
    subscriptions_canceled: int
    payments_failed: int
    paying_organisations: int = Field(
        description="A Stripe subscription that keeps its plan now: active, trialing or past_due."
    )
    mrr: float | None = Field(
        default=None, description="Unavailable until LEKA keeps invoices (LEKA-554)."
    )
    arr: float | None = Field(
        default=None, description="Unavailable until LEKA keeps invoices (LEKA-554)."
    )


class AdminTechnical(BaseModel):
    sources_in_error: int
    sync_failures: int
    jobs_failed: int


class AdminPoint(BaseModel):
    at: datetime
    value: float


class AdminOverview(BaseModel):
    window: AdminWindow
    acquisition: AdminAcquisition
    activity: AdminActivity
    product: AdminProduct
    business: AdminBusiness
    technical: AdminTechnical
    series: dict[str, list[AdminPoint]]


def window_of(
    period: Period,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> AdminWindow:
    moment = now or datetime.now(UTC)
    today = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "custom":
        if start is None or end is None or start >= end:
            raise ValueError("a custom period has a start before its end")
        if end - start > timedelta(days=731):
            raise ValueError("a period of two years at most")
        lower, upper = start, end
    elif period == "today":
        lower, upper = today, moment
    else:
        lower, upper = moment - timedelta(days=PERIOD_DAYS[period]), moment
    return AdminWindow(
        period=period,
        start=lower,
        end=upper,
        bucket="day" if upper - lower <= timedelta(days=92) else "month",
    )


def _real() -> Any:
    """Not a demonstration organisation (or none at all)."""
    demo = select(Workspace.id).where(Workspace.demo.is_(True))
    return or_(
        ActivityEvent.for_workspace_id.is_(None), ActivityEvent.for_workspace_id.not_in(demo)
    )


async def _count(session: AsyncSession, statement: Any) -> int:
    return int(await session.scalar(statement) or 0)


async def _kinds(session: AsyncSession, window: AdminWindow, *kinds: str) -> int:
    return await _count(
        session,
        select(func.count()).where(
            ActivityEvent.kind.in_(kinds),
            ActivityEvent.at >= window.start,
            ActivityEvent.at < window.end,
            _real(),
        ),
    )


async def _active(session: AsyncSession, since: datetime, until: datetime) -> int:
    return await _count(
        session,
        select(func.count(distinct(ActivityEvent.user_id))).where(
            ActivityEvent.kind == "user.active",
            ActivityEvent.at >= since,
            ActivityEvent.at < until,
            _real(),
        ),
    )


async def _series(
    session: AsyncSession, window: AdminWindow, kind: str, *, distinct_users: bool = False
) -> list[AdminPoint]:
    bucket = func.date_trunc(window.bucket, ActivityEvent.at)
    measure = func.count(distinct(ActivityEvent.user_id)) if distinct_users else func.count()
    rows = await session.execute(
        select(bucket, measure)
        .where(
            ActivityEvent.kind == kind,
            ActivityEvent.at >= window.start,
            ActivityEvent.at < window.end,
            _real(),
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    return [AdminPoint(at=at, value=float(value)) for at, value in rows.all()]


async def _credit_series(session: AsyncSession, window: AdminWindow) -> list[AdminPoint]:
    bucket = func.date_trunc(window.bucket, UsageRecord.started_at)
    rows = await session.execute(
        select(bucket, func.sum(UsageRecord.leka_cost_usd))
        .where(
            UsageRecord.started_at >= window.start,
            UsageRecord.started_at < window.end,
            UsageRecord.leka_cost_usd.is_not(None),
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    return [
        AdminPoint(at=at, value=round(float(total) / settings.credit_usd, 2))
        for at, total in rows.all()
        if total is not None
    ]


async def overview(
    session: AsyncSession, window: AdminWindow, *, now: datetime | None = None
) -> AdminOverview:
    moment = now or datetime.now(UTC)
    today = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    in_window = (Workspace.created_at >= window.start) & (Workspace.created_at < window.end)
    real = Workspace.demo.is_(False)

    latest = (
        select(WorkspacePlan.workspace_id, WorkspacePlan.plan)
        .distinct(WorkspacePlan.workspace_id)
        .order_by(
            WorkspacePlan.workspace_id, WorkspacePlan.at.desc(), WorkspacePlan.created_at.desc()
        )
        .subquery()
    )
    plans = await session.execute(
        select(latest.c.plan, func.count())
        .select_from(Workspace)
        .outerjoin(latest, latest.c.workspace_id == Workspace.id)
        .where(real)
        .group_by(latest.c.plan)
    )
    by_plan: dict[str, int] = {}
    for plan, count in plans.all():
        # Never put on a plan: Free.
        by_plan[plan or "free"] = by_plan.get(plan or "free", 0) + int(count)

    runs_where = [AgentRun.queued_at >= window.start, AgentRun.queued_at < window.end]
    runs = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(AgentRun.status == "succeeded"),
                func.count().filter(AgentRun.status == "failed"),
                func.count(distinct(AgentRun.key)),
                func.count(distinct(AgentRun.workspace_id)),
            ).where(
                *runs_where,
                AgentRun.workspace_id.not_in(select(Workspace.id).where(Workspace.demo.is_(True))),
            )
        )
    ).one()
    total, succeeded, failed, agents, organisations = (int(v or 0) for v in runs)
    cost = await session.scalar(
        select(func.sum(UsageRecord.leka_cost_usd)).where(
            UsageRecord.started_at >= window.start, UsageRecord.started_at < window.end
        )
    )

    return AdminOverview(
        window=window,
        acquisition=AdminAcquisition(
            organisations=await _count(
                session, select(func.count()).select_from(Workspace).where(real)
            ),
            organisations_new=await _count(
                session, select(func.count()).select_from(Workspace).where(real, in_window)
            ),
            users=await _count(session, select(func.count()).select_from(User)),
            users_new=await _count(
                session,
                select(func.count()).where(
                    User.created_at >= window.start, User.created_at < window.end
                ),
            ),
            by_plan=by_plan,
        ),
        activity=AdminActivity(
            dau=await _active(session, today, moment + timedelta(seconds=1)),
            wau=await _active(session, moment - timedelta(days=7), moment + timedelta(seconds=1)),
            mau=await _active(session, moment - timedelta(days=30), moment + timedelta(seconds=1)),
            intentions_created=await _kinds(session, window, "intention.created"),
            intentions_completed=await _kinds(session, window, "intention.completed"),
            intentions_failed=await _kinds(session, window, "intention.failed"),
        ),
        product=AdminProduct(
            agent_runs=total,
            agent_success_rate=round(succeeded / (succeeded + failed), 4)
            if succeeded + failed
            else None,
            agents_used=agents,
            organisations_running_agents=organisations,
            credits_consumed=round(float(cost) / settings.credit_usd, 2)
            if cost is not None
            else None,
        ),
        business=AdminBusiness(
            subscriptions_started=await _kinds(session, window, "subscription.started"),
            subscriptions_canceled=await _kinds(session, window, "subscription.canceled"),
            payments_failed=await _kinds(session, window, "payment.failed"),
            paying_organisations=await _count(
                session,
                select(func.count()).where(BillingAccount.status.in_(PAYING)),
            ),
        ),
        technical=AdminTechnical(
            sources_in_error=await _count(
                session,
                select(func.count()).where(
                    or_(
                        Source.status == SourceStatus.ERROR,
                        Source.health_status == HealthStatus.UNHEALTHY,
                    )
                ),
            ),
            sync_failures=await _kinds(session, window, "sync.failed"),
            jobs_failed=await _count(
                session,
                select(func.count()).where(
                    JobRun.status == "failed",
                    JobRun.finished_at >= window.start,
                    JobRun.finished_at < window.end,
                ),
            ),
        ),
        series={
            "users_new": await _series(session, window, "user.signed_up"),
            "users_active": await _series(session, window, "user.active", distinct_users=True),
            "intentions_created": await _series(session, window, "intention.created"),
            "credits_consumed": await _credit_series(session, window),
        },
    )
