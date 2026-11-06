"""The figures of LEKA ADMIN's home (LEKA-544, LEKA-548), over a period.

Each figure is read from real rows; docs/admin/indicateurs.md defines each
one and how it is computed. Demonstration organisations (LEKA-449) are left
out of every figure, and so is a Stripe event no organisation of LEKA's
answers for. What LEKA does not know is null, never 0, and said why.

  acquisition   organisations and people, all and new in the period; the
                organisations by plan now, Free and paid
  activity      people active today, in 7 days, in 30 days (the journal's
                user.active); the organisations active in the period;
                intentions asked, completed, failed, their success rate;
                analyses ended with a result, failed
  product       agent runs, their success rate, the agents used, the most
                used; the active organisations that ran one; credits used
  business      revenue now (MRR, ARR: the paying subscriptions' prices,
                coupons off, VAT out) apart from the money collected in the
                period (invoices paid, VAT in) and refunded; subscriptions
                started, cancelled, churn; payments failed. Amounts need
                billing:read: without it, null and `amounts_granted` false
  costs         what LEKA's models cost LEKA in the period, apart from both
  technical     incidents firing now (the ops watch's alerts); sources in
                error now; syncs and background jobs failed in the period
  intelligence  of the organisations created in the period: activated, time
                to first value, converted to a paid plan; and the people's
                monthly retention by the month they signed up
  recent        the latest sign-ups, organisations, subscriptions, failed
                payments and intentions, whatever the period
  series        per day (per month past 90 days): organisations and people
                in all, people signed up and active, intentions asked,
                credits used, the MRR as it stood each day
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.models import ActivityEvent, AdminDailyFigure
from leka.admin.schemas import OrganisationRef
from leka.background import JobRun
from leka.billing import PAYING, AgentEntitlement, BillingAccount, StripeEvent, monthly
from leka.capabilities import AgentRun
from leka.connectors import HealthStatus, Source, SourceStatus
from leka.core.config import settings
from leka.governance import WorkspacePlan
from leka.identity import User
from leka.intentions import IntentionAnalysis, IntentionEvent
from leka.metering import UsageRecord
from leka.ops import firing_now
from leka.platform import Workspace

Period = Literal["today", "7d", "30d", "90d", "12m", "custom"]
PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}
CURRENCY = "eur"
# An analysis that ended with a result, whole or in part; « blocked » asks the
# person a question and « stopped » was stopped by them: neither ended, nor failed.
ANALYSED = ("complete", "partial", "inconclusive")
# Seen in the product, or asked something: what makes an organisation active.
ACTIVE_KINDS = ("user.active", "intention.created")
RECENT: dict[str, tuple[str, ...]] = {
    "signups": ("user.signed_up", "workspace.created"),
    "billing": (
        "subscription.started",
        "subscription.changed",
        "subscription.canceled",
        "payment.failed",
        "refund.issued",
    ),
    "intentions": ("intention.created", "intention.failed"),
}
RECENT_EACH = 8
# The monthly retention: this many months of sign-ups, followed this many after.
COHORTS = 6
FOLLOWED = 5


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
    organisations_free: int = Field(description="On the Free plan now.")
    organisations_paid: int = Field(description="On any other plan now, paid by Stripe or not.")


class AdminActivity(BaseModel):
    dau: int = Field(description="People seen in the product today (UTC).")
    wau: int = Field(description="…in the last 7 days.")
    mau: int = Field(description="…in the last 30 days.")
    organisations_active: int = Field(
        description="Organisations someone was seen in, or asked an intention in, in the period."
    )
    intentions_created: int
    intentions_completed: int
    intentions_failed: int
    intention_success_rate: float | None = Field(
        description="Completed out of those that ended completed or failed; null: none."
    )
    analyses_completed: int = Field(description="Ended with a result, whole or in part.")
    analyses_failed: int


class AdminTopAgent(BaseModel):
    key: str
    runs: int
    succeeded: int
    failed: int


class AdminProduct(BaseModel):
    agent_runs: int
    agent_success_rate: float | None = Field(
        description="Succeeded out of the runs that ended; null: none."
    )
    agents_used: int
    organisations_running_agents: int
    agent_adoption_rate: float | None = Field(
        description="Of the active organisations, the share that ran an agent; null: none active."
    )
    top_agents: list[AdminTopAgent] = Field(description="The five most run, in the period.")
    credits_consumed: float | None = Field(description="Null: no cost LEKA could measure.")


class AdminBusiness(BaseModel):
    amounts_granted: bool = Field(
        description="False: the admin's role does not read billing; every amount is null."
    )
    currency: Literal["EUR"] = "EUR"
    mrr: float | None = Field(
        description="Monthly recurring revenue now: each paying subscription's price, coupons "
        "off, VAT out; trials and plans paid outside Stripe left out. Null: no price known."
    )
    arr: float | None = Field(description="The MRR times twelve.")
    mrr_subscriptions: int = Field(description="Paying subscriptions counted in the MRR.")
    mrr_unknown: int = Field(description="Paying subscriptions whose price LEKA does not know.")
    trialing: int = Field(description="Subscriptions in their trial: not revenue yet.")
    paid_outside_stripe: int = Field(
        description="Organisations on a paid plan with no paying Stripe subscription (a "
        "contract, an account of LEKA's team): not in the MRR."
    )
    collected: float | None = Field(
        description="Money collected in the period: the invoices paid, VAT in. Null: not kept."
    )
    collected_tax: float | None = Field(description="The VAT within it.")
    collected_unknown: int = Field(
        description="Invoices paid in the period whose amount LEKA did not keep (before LEKA-548)."
    )
    refunded: float | None = Field(description="Refunded in the period.")
    subscriptions_started: int
    subscriptions_canceled: int
    churn_rate: float | None = Field(
        description="Cancelled in the period out of those paying at its start; null: none."
    )
    payments_failed: int
    paying_organisations: int = Field(
        description="A Stripe subscription that keeps its plan now: active, trialing or past_due."
    )


class AdminCosts(BaseModel):
    amounts_granted: bool
    ai_usd: float | None = Field(
        description="What LEKA's models cost LEKA in the period, in US dollars; null: not known."
    )
    ai_incomplete: int = Field(
        description="Executions of the period whose model cost is known in part or not at all."
    )
    infrastructure_usd: float | None = Field(
        default=None, description="Not measured by LEKA (usage_records.infra_cost)."
    )


class AdminIncident(BaseModel):
    rule: str
    severity: str = Field(description="critical: someone acts now; warning: today.")
    title: str
    since: datetime
    why: str | None


class AdminTechnical(BaseModel):
    incidents: list[AdminIncident] | None = Field(
        description="Firing now, as the ops watch judged it; null: it cannot be read."
    )
    sources_in_error: int
    sync_failures: int
    jobs_failed: int


class AdminCohort(BaseModel):
    month: date = Field(description="The month its people signed up.")
    size: int
    retained: list[float | None] = Field(
        description="Month by month after it, the share of them seen in the product; null: "
        "that month has not come, or LEKA did not track activity yet."
    )


class AdminIntelligence(BaseModel):
    organisations_created: int = Field(description="Created in the period: who the rest is of.")
    activated: int = Field(description="Of them, those with an intention completed since.")
    activation_rate: float | None
    time_to_first_value_hours: float | None = Field(
        description="Median, from an organisation's creation to its first intention completed."
    )
    converted: int = Field(description="Of them, those that started a Stripe subscription since.")
    conversion_rate: float | None
    retention: list[AdminCohort]
    tracked_since: datetime | None = Field(
        description="The first activity LEKA recorded: retention before it is not known."
    )


class AdminRecent(BaseModel):
    id: uuid.UUID
    kind: str
    at: datetime
    organisation: OrganisationRef | None
    user_id: uuid.UUID | None
    properties: dict[str, object]


class AdminPoint(BaseModel):
    at: datetime
    value: float


class AdminOverview(BaseModel):
    window: AdminWindow
    acquisition: AdminAcquisition
    activity: AdminActivity
    product: AdminProduct
    business: AdminBusiness
    costs: AdminCosts
    technical: AdminTechnical
    intelligence: AdminIntelligence
    recent: list[AdminRecent]
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


def _demo() -> Any:
    return select(Workspace.id).where(Workspace.demo.is_(True))


def _real() -> Any:
    """Not a demonstration organisation (or none at all)."""
    return or_(
        ActivityEvent.for_workspace_id.is_(None), ActivityEvent.for_workspace_id.not_in(_demo())
    )


def _answered() -> Any:
    """A Stripe event an organisation of LEKA's answers for, and applied."""
    return (
        ActivityEvent.for_workspace_id.is_not(None)
        & ActivityEvent.for_workspace_id.not_in(_demo())
        & (ActivityEvent.properties["outcome"].astext == "applied")
    )


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _euros(cents: float) -> float:
    return round(cents / 100, 2)


async def _count(session: AsyncSession, statement: Any) -> int:
    return int(await session.scalar(statement) or 0)


async def _kinds(session: AsyncSession, window: AdminWindow, *kinds: str) -> int:
    stripe = kinds[0].startswith(("subscription.", "payment.", "refund."))
    return await _count(
        session,
        select(func.count()).where(
            ActivityEvent.kind.in_(kinds),
            ActivityEvent.at >= window.start,
            ActivityEvent.at < window.end,
            _answered() if stripe else _real(),
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


def _next(at: datetime, bucket: str) -> datetime:
    return at + timedelta(days=1) if bucket == "day" else (at + timedelta(days=32)).replace(day=1)


def buckets(window: AdminWindow) -> list[datetime]:
    """Every day (or month) of the window, in UTC, from the one it starts in."""
    at = window.start.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if window.bucket == "month":
        at = at.replace(day=1)
    found: list[datetime] = []
    while at < window.end:
        found.append(at)
        at = _next(at, window.bucket)
    return found


def _bucket(window: AdminWindow, column: Any) -> Any:
    """The day (or month) a row falls in, in UTC whatever the database's zone."""
    return func.date_trunc(window.bucket, column, "UTC")


def _filled(
    window: AdminWindow, rows: Iterable[tuple[datetime, Any]], *, since: datetime | None = None
) -> list[AdminPoint]:
    """A count per bucket, 0 where nothing happened (and none before `since`)."""
    said = {at.astimezone(UTC): float(value or 0) for at, value in rows}
    return [
        AdminPoint(at=at, value=said.get(at, 0.0))
        for at in buckets(window)
        if since is None or _next(at, window.bucket) > since
    ]


async def _series(
    session: AsyncSession,
    window: AdminWindow,
    kind: str,
    *,
    distinct_users: bool = False,
    since: datetime | None = None,
) -> list[AdminPoint]:
    bucket = _bucket(window, ActivityEvent.at)
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
    )
    return _filled(window, rows.tuples().all(), since=since)


async def _totals(
    session: AsyncSession, window: AdminWindow, column: Any, *where: Any
) -> list[AdminPoint]:
    """How many there were in all at the end of each bucket."""
    before = await _count(session, select(func.count()).where(column < window.start, *where))
    bucket = _bucket(window, column)
    rows = await session.execute(
        select(bucket, func.count())
        .where(column >= window.start, column < window.end, *where)
        .group_by(bucket)
    )
    added = {at.astimezone(UTC): int(n) for at, n in rows.tuples().all()}
    points: list[AdminPoint] = []
    running = before
    for at in buckets(window):
        running += added.get(at, 0)
        points.append(AdminPoint(at=at, value=float(running)))
    return points


async def _credit_series(session: AsyncSession, window: AdminWindow) -> list[AdminPoint]:
    bucket = _bucket(window, UsageRecord.started_at)
    rows = await session.execute(
        select(bucket, func.sum(UsageRecord.leka_cost_usd))
        .where(
            UsageRecord.started_at >= window.start,
            UsageRecord.started_at < window.end,
            UsageRecord.leka_cost_usd.is_not(None),
            UsageRecord.workspace_id.not_in(_demo()),
        )
        .group_by(bucket)
    )
    measured = rows.tuples().all()
    if not measured:
        # Nothing measured in the period: not known, never a line at 0.
        return []
    return [
        AdminPoint(at=p.at, value=round(p.value / settings.credit_usd, 2))
        for p in _filled(window, measured)
    ]


async def _mrr_series(session: AsyncSession, window: AdminWindow) -> list[AdminPoint]:
    """The MRR as it stood each day (the last day of a month, by month)."""
    rows = (
        await session.execute(
            select(AdminDailyFigure.day, AdminDailyFigure.mrr)
            .where(
                AdminDailyFigure.day >= window.start.astimezone(UTC).date(),
                AdminDailyFigure.day <= window.end.astimezone(UTC).date(),
                AdminDailyFigure.mrr.is_not(None),
            )
            .order_by(AdminDailyFigure.day)
        )
    ).all()
    kept: dict[datetime, float] = {}
    for day, mrr in rows:
        at = datetime(day.year, day.month, 1 if window.bucket == "month" else day.day, tzinfo=UTC)
        kept[at] = float(mrr)
    return [AdminPoint(at=at, value=value) for at, value in kept.items()]


# ── Revenue ─────────────────────────────────────────────────────────────────


class Revenue(BaseModel):
    """What the paying subscriptions bring in a month, at a moment."""

    cents: float
    counted: int
    unknown: int
    trialing: int

    @property
    def mrr(self) -> float | None:
        # Nothing paying: a true 0. Something paying, no price known: not known.
        return _euros(self.cents) if self.counted or not self.unknown else None


async def revenue(session: AsyncSession, at: datetime) -> Revenue:
    """The plans' subscriptions, and the add-ons' — each subscription once."""
    cents, counted, unknown, trialing = 0.0, 0, 0, 0
    plans = await session.execute(
        select(BillingAccount.status, BillingAccount.recurring).where(
            BillingAccount.stripe_subscription_id.is_not(None),
            BillingAccount.status.in_(PAYING),
            BillingAccount.workspace_id.not_in(_demo()),
        )
    )
    add_ons = await session.execute(
        select(AgentEntitlement.stripe_subscription_id, AgentEntitlement.recurring).where(
            AgentEntitlement.origin == "purchase",
            AgentEntitlement.status == "active",
            AgentEntitlement.stripe_subscription_id.is_not(None),
            AgentEntitlement.workspace_id.not_in(_demo()),
        )
    )
    bought: dict[str, dict[str, Any] | None] = {}
    for subscription, recurring in add_ons.tuples().all():
        if subscription is not None and bought.get(subscription) is None:
            bought[subscription] = recurring
    each: list[tuple[str | None, dict[str, Any] | None]] = [
        (status, recurring) for status, recurring in plans.tuples().all()
    ] + [("active", recurring) for recurring in bought.values()]
    for status, recurring in each:
        if status == "trialing":
            trialing += 1
            continue
        said = (
            monthly(recurring, at)
            if recurring and str(recurring.get("currency")) == CURRENCY
            else None
        )
        if said is None:
            unknown += 1
        else:
            cents += said
            counted += 1
    return Revenue(cents=cents, counted=counted, unknown=unknown, trialing=trialing)


async def record_day(session: AsyncSession, at: datetime) -> None:
    """Today's MRR, kept for its evolution (the activity sweep, every five minutes)."""
    now = await revenue(session, at)
    values = {
        "mrr": Decimal(str(now.mrr)) if now.mrr is not None else None,
        "subscriptions": now.counted,
        "unknown": now.unknown,
        "at": at,
    }
    await session.execute(
        insert(AdminDailyFigure)
        .values(id=uuid.uuid4(), day=at.astimezone(UTC).date(), **values)
        .on_conflict_do_update(constraint="uq_admin_daily_figures_day", set_=values)
    )


async def _moved(
    session: AsyncSession, window: AdminWindow, kind: str
) -> tuple[float | None, float | None, int]:
    """What the invoices (or refunds) of the period moved: total, tax, those unknown."""
    rows = await session.execute(
        select(StripeEvent.detail).where(
            StripeEvent.type == kind,
            StripeEvent.outcome == "applied",
            StripeEvent.for_workspace_id.is_not(None),
            StripeEvent.for_workspace_id.not_in(_demo()),
            StripeEvent.received_at >= window.start,
            StripeEvent.received_at < window.end,
        )
    )
    total, tax, known, unknown = 0, 0, 0, 0
    for (detail,) in rows.all():
        amount = detail.get("amount") if isinstance(detail, dict) else None
        if not isinstance(amount, int) or detail.get("currency") != CURRENCY:
            unknown += 1
            continue
        known += 1
        total += amount
        tax += int(detail.get("tax") or 0)
    if not known and unknown:
        return None, None, unknown
    return _euros(total), _euros(tax), unknown


# ── The rest ────────────────────────────────────────────────────────────────


async def _by_plan(session: AsyncSession) -> dict[str, int]:
    latest = (
        select(WorkspacePlan.workspace_id, WorkspacePlan.plan)
        .distinct(WorkspacePlan.workspace_id)
        .order_by(
            WorkspacePlan.workspace_id, WorkspacePlan.at.desc(), WorkspacePlan.created_at.desc()
        )
        .subquery()
    )
    plans = await session.execute(
        select(Workspace.id, latest.c.plan)
        .select_from(Workspace)
        .outerjoin(latest, latest.c.workspace_id == Workspace.id)
        .where(Workspace.demo.is_(False))
    )
    by_plan: dict[str, int] = {}
    for _, plan in plans.all():
        # Never put on a plan: Free.
        by_plan[plan or "free"] = by_plan.get(plan or "free", 0) + 1
    return by_plan


async def _paid_outside_stripe(session: AsyncSession) -> int:
    latest = (
        select(WorkspacePlan.workspace_id, WorkspacePlan.plan)
        .distinct(WorkspacePlan.workspace_id)
        .order_by(
            WorkspacePlan.workspace_id, WorkspacePlan.at.desc(), WorkspacePlan.created_at.desc()
        )
        .subquery()
    )
    paying = select(BillingAccount.workspace_id).where(
        BillingAccount.status.in_(PAYING), BillingAccount.stripe_subscription_id.is_not(None)
    )
    return await _count(
        session,
        select(func.count())
        .select_from(Workspace)
        .join(latest, latest.c.workspace_id == Workspace.id)
        .where(
            Workspace.demo.is_(False),
            latest.c.plan != "free",
            Workspace.id.not_in(paying),
        ),
    )


async def _organisations_active(session: AsyncSession, window: AdminWindow) -> set[uuid.UUID]:
    rows = await session.scalars(
        select(distinct(ActivityEvent.for_workspace_id)).where(
            ActivityEvent.kind.in_(ACTIVE_KINDS),
            ActivityEvent.at >= window.start,
            ActivityEvent.at < window.end,
            ActivityEvent.for_workspace_id.is_not(None),
            ActivityEvent.for_workspace_id.not_in(_demo()),
        )
    )
    return {i for i in rows.all() if i is not None}


async def _agents(
    session: AsyncSession, window: AdminWindow, active: set[uuid.UUID]
) -> AdminProduct:
    where = [
        AgentRun.queued_at >= window.start,
        AgentRun.queued_at < window.end,
        AgentRun.workspace_id.not_in(_demo()),
    ]
    total, succeeded, failed, agents = (
        int(v or 0)
        for v in (
            await session.execute(
                select(
                    func.count(),
                    func.count().filter(AgentRun.status == "succeeded"),
                    func.count().filter(AgentRun.status == "failed"),
                    func.count(distinct(AgentRun.key)),
                ).where(*where)
            )
        ).one()
    )
    running = set(await session.scalars(select(distinct(AgentRun.workspace_id)).where(*where)))
    top = await session.execute(
        select(
            AgentRun.key,
            func.count(),
            func.count().filter(AgentRun.status == "succeeded"),
            func.count().filter(AgentRun.status == "failed"),
        )
        .where(*where)
        .group_by(AgentRun.key)
        .order_by(func.count().desc(), AgentRun.key)
        .limit(5)
    )
    cost = await session.scalar(
        select(func.sum(UsageRecord.leka_cost_usd)).where(
            UsageRecord.started_at >= window.start,
            UsageRecord.started_at < window.end,
            UsageRecord.workspace_id.not_in(_demo()),
        )
    )
    return AdminProduct(
        agent_runs=total,
        agent_success_rate=_rate(succeeded, succeeded + failed),
        agents_used=agents,
        organisations_running_agents=len(running),
        agent_adoption_rate=_rate(len(running & active), len(active)),
        top_agents=[
            AdminTopAgent(key=key, runs=int(runs), succeeded=int(ok), failed=int(ko))
            for key, runs, ok, ko in top.tuples().all()
        ],
        credits_consumed=round(float(cost) / settings.credit_usd, 2) if cost is not None else None,
    )


async def _costs(session: AsyncSession, window: AdminWindow, *, granted: bool) -> AdminCosts:
    where = [
        UsageRecord.started_at >= window.start,
        UsageRecord.started_at < window.end,
        UsageRecord.workspace_id.not_in(_demo()),
    ]
    cost, incomplete = (
        await session.execute(
            select(
                func.sum(UsageRecord.leka_cost_usd),
                func.count().filter(UsageRecord.cost_status.in_(("partial", "unknown"))),
            ).where(*where)
        )
    ).one()
    return AdminCosts(
        amounts_granted=granted,
        ai_usd=round(float(cost), 2) if granted and cost is not None else None,
        ai_incomplete=int(incomplete or 0),
    )


async def _incidents() -> list[AdminIncident] | None:
    firing = await firing_now()
    if firing is None:
        return None
    return [
        AdminIncident(
            rule=a.rule.name, severity=a.rule.severity, title=a.rule.title, since=a.since, why=a.why
        )
        for a in firing
    ]


async def _intelligence(
    session: AsyncSession, window: AdminWindow, moment: datetime, tracked: datetime | None
) -> AdminIntelligence:
    created = dict(
        (
            await session.execute(
                select(Workspace.id, Workspace.created_at).where(
                    Workspace.demo.is_(False),
                    Workspace.created_at >= window.start,
                    Workspace.created_at < window.end,
                )
            )
        )
        .tuples()
        .all()
    )
    first: dict[uuid.UUID, datetime] = {}
    converted: set[uuid.UUID] = set()
    if created:
        first = dict(
            (
                await session.execute(
                    select(IntentionEvent.workspace_id, func.min(IntentionEvent.at))
                    .where(
                        IntentionEvent.workspace_id.in_(created),
                        IntentionEvent.to_status == "completed",
                    )
                    .group_by(IntentionEvent.workspace_id)
                )
            )
            .tuples()
            .all()
        )
        converted = {
            i
            for i in await session.scalars(
                select(distinct(ActivityEvent.for_workspace_id)).where(
                    ActivityEvent.kind == "subscription.started",
                    ActivityEvent.for_workspace_id.in_(created),
                    ActivityEvent.properties["outcome"].astext == "applied",
                )
            )
            if i is not None
        }
    hours = [
        (at - created[workspace]).total_seconds() / 3600
        for workspace, at in first.items()
        if at >= created[workspace]
    ]
    return AdminIntelligence(
        organisations_created=len(created),
        activated=len(first),
        activation_rate=_rate(len(first), len(created)),
        time_to_first_value_hours=round(median(hours), 1) if hours else None,
        converted=len(converted),
        conversion_rate=_rate(len(converted), len(created)),
        retention=await _retention(session, moment, tracked),
        tracked_since=tracked,
    )


def _month(at: datetime, plus: int = 0) -> date:
    index = at.year * 12 + at.month - 1 + plus
    return date(index // 12, index % 12 + 1, 1)


def cohorts(
    signed_up: Sequence[tuple[uuid.UUID, datetime]],
    seen: Sequence[tuple[uuid.UUID, datetime]],
    *,
    now: datetime,
    tracked_since: datetime | None,
) -> list[AdminCohort]:
    """The people of each of the last COHORTS months of sign-ups, and the
    share of them seen in each of the FOLLOWED months after. Pure."""
    this_month = _month(now)
    months = [_month(now, -k) for k in range(COHORTS - 1, -1, -1)]
    people: dict[date, set[uuid.UUID]] = defaultdict(set)
    for user, at in signed_up:
        people[_month(at)].add(user)
    active: dict[date, set[uuid.UUID]] = defaultdict(set)
    for user, at in seen:
        active[_month(at)].add(user)
    tracked = _month(tracked_since) if tracked_since else None
    found: list[AdminCohort] = []
    for month in months:
        cohort = people.get(month, set())
        retained: list[float | None] = []
        for k in range(1, FOLLOWED + 1):
            target = _month(datetime(month.year, month.month, 1, tzinfo=UTC), k)
            if target > this_month or tracked is None or target < tracked or not cohort:
                retained.append(None)
            else:
                retained.append(round(len(cohort & active.get(target, set())) / len(cohort), 4))
        found.append(AdminCohort(month=month, size=len(cohort), retained=retained))
    return found


async def _retention(
    session: AsyncSession, moment: datetime, tracked: datetime | None
) -> list[AdminCohort]:
    first = _month(moment, -(COHORTS - 1))
    since = datetime(first.year, first.month, 1, tzinfo=UTC)
    signed_up = (
        await session.execute(select(User.id, User.created_at).where(User.created_at >= since))
    ).tuples()
    seen = (
        await session.execute(
            select(ActivityEvent.user_id, ActivityEvent.at).where(
                ActivityEvent.kind == "user.active",
                ActivityEvent.at >= since,
                ActivityEvent.user_id.is_not(None),
                _real(),
            )
        )
    ).tuples()
    return cohorts(
        signed_up.all(),
        [(user, at) for user, at in seen.all() if user is not None],
        now=moment,
        tracked_since=tracked,
    )


async def _recent(session: AsyncSession) -> list[AdminRecent]:
    rows: list[ActivityEvent] = []
    for kinds in RECENT.values():
        stripe = kinds[0].startswith("subscription.")
        rows += (
            await session.scalars(
                select(ActivityEvent)
                .where(ActivityEvent.kind.in_(kinds), _answered() if stripe else _real())
                .order_by(ActivityEvent.at.desc())
                .limit(RECENT_EACH)
            )
        ).all()
    rows.sort(key=lambda e: e.at, reverse=True)
    wanted = {e.for_workspace_id for e in rows if e.for_workspace_id is not None}
    names = (
        dict(
            (
                await session.execute(
                    select(Workspace.id, Workspace.name).where(Workspace.id.in_(wanted))
                )
            )
            .tuples()
            .all()
        )
        if wanted
        else {}
    )
    return [
        AdminRecent(
            id=e.id,
            kind=e.kind,
            at=e.at,
            organisation=OrganisationRef(id=e.for_workspace_id, name=names[e.for_workspace_id])
            if e.for_workspace_id in names
            else None,
            user_id=e.user_id,
            properties=e.properties,
        )
        for e in rows
    ]


async def overview(
    session: AsyncSession,
    window: AdminWindow,
    *,
    amounts: bool = True,
    now: datetime | None = None,
) -> AdminOverview:
    moment = now or datetime.now(UTC)
    today = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    in_window = (Workspace.created_at >= window.start) & (Workspace.created_at < window.end)
    real = Workspace.demo.is_(False)
    later = moment + timedelta(seconds=1)

    by_plan = await _by_plan(session)
    active = await _organisations_active(session, window)
    completed = await _kinds(session, window, "intention.completed")
    failed = await _kinds(session, window, "intention.failed")
    analysed, analyses_failed = (
        int(v or 0)
        for v in (
            await session.execute(
                select(
                    func.count().filter(IntentionAnalysis.status.in_(ANALYSED)),
                    func.count().filter(IntentionAnalysis.status == "failed"),
                ).where(
                    IntentionAnalysis.finished_at >= window.start,
                    IntentionAnalysis.finished_at < window.end,
                    IntentionAnalysis.workspace_id.not_in(_demo()),
                )
            )
        ).one()
    )

    now_revenue = await revenue(session, moment)
    collected, tax, collected_unknown = await _moved(session, window, "invoice.paid")
    refunded, _, _ = await _moved(session, window, "charge.refunded")
    started = await _kinds(session, window, "subscription.started")
    canceled = await _kinds(session, window, "subscription.canceled")
    paying = await _count(
        session,
        select(func.count()).where(
            BillingAccount.status.in_(PAYING), BillingAccount.workspace_id.not_in(_demo())
        ),
    )
    mrr = now_revenue.mrr

    tracked = await session.scalar(
        select(func.min(ActivityEvent.at)).where(ActivityEvent.kind == "user.active")
    )
    series = {
        "organisations": await _totals(session, window, Workspace.created_at, real),
        "users": await _totals(session, window, User.created_at),
        "users_new": await _series(session, window, "user.signed_up"),
        "users_active": await _series(
            session, window, "user.active", distinct_users=True, since=tracked
        ),
        "intentions_created": await _series(session, window, "intention.created"),
        "credits_consumed": await _credit_series(session, window),
    }
    if amounts:
        series["mrr"] = await _mrr_series(session, window)

    return AdminOverview(
        window=window,
        acquisition=AdminAcquisition(
            organisations=sum(by_plan.values()),
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
            organisations_free=by_plan.get("free", 0),
            organisations_paid=sum(n for plan, n in by_plan.items() if plan != "free"),
        ),
        activity=AdminActivity(
            dau=await _active(session, today, later),
            wau=await _active(session, moment - timedelta(days=7), later),
            mau=await _active(session, moment - timedelta(days=30), later),
            organisations_active=len(active),
            intentions_created=await _kinds(session, window, "intention.created"),
            intentions_completed=completed,
            intentions_failed=failed,
            intention_success_rate=_rate(completed, completed + failed),
            analyses_completed=analysed,
            analyses_failed=analyses_failed,
        ),
        product=await _agents(session, window, active),
        business=AdminBusiness(
            amounts_granted=amounts,
            mrr=mrr if amounts else None,
            arr=round(mrr * 12, 2) if amounts and mrr is not None else None,
            mrr_subscriptions=now_revenue.counted,
            mrr_unknown=now_revenue.unknown,
            trialing=now_revenue.trialing,
            paid_outside_stripe=await _paid_outside_stripe(session),
            collected=collected if amounts else None,
            collected_tax=tax if amounts else None,
            collected_unknown=collected_unknown,
            refunded=refunded if amounts else None,
            subscriptions_started=started,
            subscriptions_canceled=canceled,
            # Paying at the start: those paying now, less those started, plus
            # those cancelled in the period.
            churn_rate=_rate(canceled, paying - started + canceled)
            if paying - started + canceled > 0
            else None,
            payments_failed=await _kinds(session, window, "payment.failed"),
            paying_organisations=paying,
        ),
        costs=await _costs(session, window, granted=amounts),
        technical=AdminTechnical(
            incidents=await _incidents(),
            sources_in_error=await _count(
                session,
                select(func.count()).where(
                    or_(
                        Source.status == SourceStatus.ERROR,
                        Source.health_status == HealthStatus.UNHEALTHY,
                    ),
                    Source.workspace_id.not_in(_demo()),
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
        intelligence=await _intelligence(session, window, moment, tracked),
        recent=await _recent(session),
        series=series,
    )
