"""AI credits across LEKA, for LEKA's team (LEKA-553): every organisation's
ledger, line by line; each month of it reconciled with what LEKA's models
cost; this month's capacity and balance across organisations; what was
consumed by organisation, agent and model, and what it cost at the
providers' rates.

Three things kept apart, never confused:

- the commercial capacity: the credits a month gives — the plan's, the
  packs, what LEKA's team gave back or adjusted (leka.governance.plans);
- the application credits: what LEKA's models cost each organisation's
  work, in credits (`credit_usd` of cost each), and what is left;
- the providers' cost: what every call cost at the providers' rates, LEKA's
  models and an organisation's own apart — an estimate from the tokens
  each call used, never an invoice; a call with no rate is left out and
  counted, never guessed.

Read inside `system_scope()` like every admin read (leka/admin/reads.py).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.overview import AdminWindow, buckets
from leka.admin.reads import _like, _organisation_names, credits_of
from leka.admin.schemas import (
    CreditCapacity,
    CreditDay,
    CreditMonth,
    CreditMovement,
    CreditReconciliation,
    CreditsOverview,
    CreditSubject,
    CreditUse,
    OrganisationRef,
    ProviderCost,
)
from leka.capabilities import ModelCall
from leka.db import workspace_scope
from leka.governance import CreditTransaction, allowance, month_of
from leka.governance import credits_of as to_credits
from leka.metering import UsageRecord, ledger_month
from leka.platform import Workspace

RECONCILED = 0.01
TOP = 20


def _period(text: str) -> date | None:
    """A month said YYYY-MM, as its first day."""
    try:
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, 1)
    except ValueError:
        return None


# ── The ledger ───────────────────────────────────────────────────────────────


def movements_query(
    *,
    organisation_id: uuid.UUID | None = None,
    organisation: str | None = None,
    kind: str | None = None,
    origin: str | None = None,
    period: str | None = None,
    execution: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[CreditTransaction]]:
    """Every line of every ledger, or those that match."""
    statement = select(CreditTransaction)
    if organisation_id:
        statement = statement.where(CreditTransaction.workspace_id == organisation_id)
    if organisation and organisation.strip():
        pattern = _like(organisation)
        statement = statement.where(
            CreditTransaction.workspace_id.in_(
                select(Workspace.id).where(
                    or_(Workspace.name.ilike(pattern), Workspace.slug.ilike(pattern))
                )
            )
        )
    if kind:
        statement = statement.where(CreditTransaction.kind == kind)
    if origin:
        statement = statement.where(CreditTransaction.origin == origin)
    if period:
        month = _period(period)
        # A month no ledger can hold: nothing, rather than everything.
        statement = statement.where(
            CreditTransaction.period == month if month else CreditTransaction.id.is_(None)
        )
    if execution:
        statement = statement.where(CreditTransaction.execution == execution)
    if since:
        statement = statement.where(CreditTransaction.at >= since)
    if until:
        statement = statement.where(CreditTransaction.at < until)
    return statement


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


async def movement_rows(
    session: AsyncSession, lines: Sequence[CreditTransaction]
) -> list[CreditMovement]:
    names = await _organisation_names(session, (line.workspace_id for line in lines))
    return [
        CreditMovement(
            id=line.id,
            organisation=OrganisationRef(
                id=line.workspace_id, name=names.get(line.workspace_id, "")
            ),
            kind=line.kind,
            credits=round(float(line.credits), 4),
            period=line.period.strftime("%Y-%m"),
            at=line.at,
            origin=line.origin,
            reference=line.reference,
            execution=line.execution,
            subject=line.subject,
            by=line.by_whom,
            reason=line.reason,
            cost_usd=_float(line.detail.get("cost_usd")) if line.detail else None,
            cost_status=_str(line.detail.get("cost_status")) if line.detail else None,
        )
        for line in lines
    ]


# ── A month, reconciled ──────────────────────────────────────────────────────


def _months(created: datetime, now: datetime, count: int) -> list[date]:
    """The latest `count` months, this one first, none before it was created."""
    first = month_of(created)
    found: list[date] = []
    period = month_of(now)
    while period >= first and len(found) < count:
        found.append(period)
        period = (
            period.replace(year=period.year - 1, month=12)
            if period.month == 1
            else period.replace(month=period.month - 1)
        )
    return found


async def reconciliation(
    session: AsyncSession, workspace_id: uuid.UUID, *, months: int, now: datetime
) -> CreditReconciliation | None:
    """Its ledger month by month, beside the gateway: what is pending, what
    differs, what could not be priced."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return None
    read: list[CreditMonth] = []
    with workspace_scope(workspace_id):
        for period in _months(workspace.created_at, now, months):
            found = await ledger_month(session, workspace_id, period, now=now)
            gap = found.allowance_gap
            read.append(
                CreditMonth(
                    period=period.strftime("%Y-%m"),
                    granted=round(found.granted, 4),
                    packs=round(found.packs, 4),
                    refunds=round(found.refunds, 4),
                    adjustments=round(found.adjustments, 4),
                    consumed=round(found.consumed, 4),
                    expired=round(found.expired, 4),
                    balance=found.balance,
                    source=found.source,
                    pending=found.pending,
                    unpriced=found.unpriced,
                    allowance_now=found.allowance_now,
                    allowance_gap=gap,
                    closed=found.closed,
                    reconciled=abs(found.pending) < RECONCILED
                    and (gap is None or abs(gap) < RECONCILED),
                    lines=found.lines,
                    by_subject=[
                        CreditSubject(subject=subject, credits=amount)
                        for subject, amount in sorted(
                            found.by_subject.items(), key=lambda item: -item[1]
                        )
                    ],
                )
            )
    return CreditReconciliation(
        organisation=OrganisationRef(id=workspace.id, name=workspace.name),
        credits=await credits_of(session, workspace_id, now),
        months=read,
    )


# ── Across LEKA ──────────────────────────────────────────────────────────────


async def _capacity(session: AsyncSession, now: datetime) -> CreditCapacity:
    """This month, every organisation but the demonstrations'."""
    period = month_of(now)
    start = datetime.combine(period, datetime.min.time(), tzinfo=UTC)
    workspaces = (
        await session.scalars(select(Workspace.id).where(Workspace.demo.is_(False)))
    ).all()
    spent = dict(
        (
            await session.execute(
                select(ModelCall.workspace_id, func.sum(ModelCall.cost_usd))
                .where(
                    ModelCall.at >= start,
                    ModelCall.owner == "leka",
                    ModelCall.status != "failed",
                )
                .group_by(ModelCall.workspace_id)
            )
        )
        .tuples()
        .all()
    )
    plans = packs = adjustments = 0
    used = remaining = 0.0
    exhausted = 0
    for workspace_id in workspaces:
        with workspace_scope(workspace_id):
            given = await allowance(session, workspace_id, now)
        consumed = round(to_credits(float(spent.get(workspace_id) or 0.0)), 2)
        plans += given.plan.monthly_credits
        packs += given.packs
        adjustments += given.adjustments
        used += consumed
        left = max(given.credits - consumed, 0.0)
        remaining += left
        if given.credits > 0 and left == 0:
            exhausted += 1
    capacity = plans + packs + adjustments
    return CreditCapacity(
        period=period.strftime("%Y-%m"),
        organisations=len(workspaces),
        capacity=capacity,
        plans=plans,
        packs=packs,
        adjustments=adjustments,
        used=round(used, 2),
        remaining=round(remaining, 2),
        utilisation=round(used / capacity, 4) if capacity else None,
        exhausted=exhausted,
    )


async def credits_overview(
    session: AsyncSession, window: AdminWindow, *, now: datetime
) -> CreditsOverview:
    calls: list[Any] = [
        ModelCall.at >= window.start,
        ModelCall.at < window.end,
        ModelCall.status != "failed",
    ]
    leka = [*calls, ModelCall.owner == "leka"]

    by_workspace = (
        (
            await session.execute(
                select(ModelCall.workspace_id, func.sum(ModelCall.cost_usd))
                .where(*leka, ModelCall.cost_usd.is_not(None))
                .group_by(ModelCall.workspace_id)
                .order_by(func.sum(ModelCall.cost_usd).desc())
                .limit(TOP)
            )
        )
        .tuples()
        .all()
    )
    names = await _organisation_names(session, (row[0] for row in by_workspace))

    by_model = (
        (
            await session.execute(
                select(ModelCall.provider, ModelCall.model, func.sum(ModelCall.cost_usd))
                .where(*leka, ModelCall.cost_usd.is_not(None))
                .group_by(ModelCall.provider, ModelCall.model)
                .order_by(func.sum(ModelCall.cost_usd).desc())
            )
        )
        .tuples()
        .all()
    )

    by_agent = (
        (
            await session.execute(
                select(UsageRecord.kind, UsageRecord.subject, func.sum(UsageRecord.leka_cost_usd))
                .where(
                    UsageRecord.started_at >= window.start,
                    UsageRecord.started_at < window.end,
                    UsageRecord.leka_cost_usd.is_not(None),
                )
                .group_by(UsageRecord.kind, UsageRecord.subject)
                .order_by(func.sum(UsageRecord.leka_cost_usd).desc())
            )
        )
        .tuples()
        .all()
    )

    bucket = func.date_trunc(window.bucket, ModelCall.at, "UTC")
    per_bucket = {
        at.astimezone(UTC): float(total or 0.0)
        for at, total in (
            await session.execute(
                select(bucket, func.sum(ModelCall.cost_usd))
                .where(*leka, ModelCall.cost_usd.is_not(None))
                .group_by(bucket)
            )
        )
        .tuples()
        .all()
    }

    owned = dict(
        (
            await session.execute(
                select(ModelCall.owner, func.coalesce(func.sum(ModelCall.cost_usd), 0.0))
                .where(*calls)
                .group_by(ModelCall.owner)
            )
        )
        .tuples()
        .all()
    )
    unpriced = await session.scalar(
        select(func.count()).where(*calls, ModelCall.cost_usd.is_(None))
    )
    leka_usd = float(owned.get("leka") or 0.0)

    def use(key: str, label: str | None, cost: object) -> CreditUse:
        usd = float(cost) if cost is not None else None  # type: ignore[arg-type]
        return CreditUse(
            key=key,
            label=label,
            credits=round(to_credits(usd), 2) if usd is not None else 0.0,
            cost_usd=round(usd, 6) if usd is not None else None,
        )

    return CreditsOverview(
        month=await _capacity(session, now),
        since=window.start,
        until=window.end,
        consumed=round(to_credits(leka_usd), 2),
        by_organisation=[use(str(w), names.get(w), cost) for w, cost in by_workspace],
        by_agent=[use(subject, kind, cost) for kind, subject, cost in by_agent],
        by_model=[use(f"{provider}/{model}", provider, cost) for provider, model, cost in by_model],
        series=[
            CreditDay(at=at, credits=round(to_credits(per_bucket.get(at, 0.0)), 2))
            for at in buckets(window)
        ],
        provider_cost=ProviderCost(
            leka_usd=round(leka_usd, 6),
            workspace_usd=round(float(owned.get("workspace") or 0.0), 6),
            unpriced_calls=int(unpriced or 0),
        ),
    )


__all__ = [
    "credits_overview",
    "movement_rows",
    "movements_query",
    "reconciliation",
]
