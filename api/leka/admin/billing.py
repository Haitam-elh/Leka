"""Subscriptions, billing and finance, for LEKA's team (LEKA-554): Stripe the
source of truth, read from what its events said and LEKA kept
(leka.billing.history), never a figure of its own.

Three things kept apart, never confused (docs/admin/indicateurs.md):

- recurring revenue: the MRR, each paying subscription's price a month now,
  coupons taken off while they last (leka.admin.overview.revenue); its
  movements explained by each subscription's changes;
- billing: what the invoices said was owed, prorations included;
- collection: what the payments took, less what refunds gave back.

In euros: the MRR excluding VAT, what was billed and collected as Stripe
charged it, VAT included (said apart); an amount said in another currency is
counted apart, never converted. Read inside `system_scope()` like every admin read.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.models import AdminDailyFigure
from leka.admin.overview import AdminWindow, revenue
from leka.admin.reads import _like, _organisation_names
from leka.admin.schemas import (
    FinanceOverview,
    InvoiceLine,
    InvoiceRow,
    MrrMovement,
    OrganisationRef,
    PaymentRow,
    PlanRevenue,
    RefundRow,
    SubscriptionAddOn,
    SubscriptionChangeRow,
    SubscriptionDetail,
    SubscriptionDiscount,
    SubscriptionRow,
)
from leka.billing import (
    AgentEntitlement,
    BillingAccount,
    BillingInvoice,
    BillingPayment,
    BillingRefund,
    StripeEvent,
    SubscriptionChange,
    mrr_of,
)
from leka.platform import Workspace

CURRENCY = "eur"
EARNING = ("active", "past_due")
LATEST = 12


def _eur(cents: float | int | None) -> float | None:
    return round(cents / 100, 2) if cents is not None else None


def _real(column: Any) -> Any:
    """Not a demonstration organisation: the figures leave them out, like
    the dashboard's MRR (leka.admin.overview.revenue)."""
    return column.not_in(select(Workspace.id).where(Workspace.demo.is_(True)))


def _named(column: Any, organisation: str | None) -> list[Any]:
    if not organisation or not organisation.strip():
        return []
    pattern = _like(organisation)
    return [
        column.in_(
            select(Workspace.id).where(
                or_(Workspace.name.ilike(pattern), Workspace.slug.ilike(pattern))
            )
        )
    ]


# ── Subscriptions ────────────────────────────────────────────────────────────


def subscriptions_query(
    *,
    plan: str | None = None,
    status: str | None = None,
    interval: str | None = None,
    organisation: str | None = None,
) -> Select[tuple[BillingAccount]]:
    statement = select(BillingAccount)
    if plan:
        statement = statement.where(BillingAccount.plan == plan)
    if status:
        statement = statement.where(BillingAccount.status == status)
    if interval:
        statement = statement.where(BillingAccount.interval == interval)
    return statement.where(*_named(BillingAccount.workspace_id, organisation))


def _discount(recurring: dict[str, Any] | None) -> SubscriptionDiscount | None:
    said = (recurring or {}).get("discount")
    if not isinstance(said, dict):
        return None
    ends = said.get("ends")
    return SubscriptionDiscount(
        percent_off=float(said["percent_off"]) if said.get("percent_off") is not None else None,
        amount_off_eur=_eur(said.get("amount_off")),
        ends=datetime.fromisoformat(str(ends)) if ends else None,
    )


def _price(recurring: dict[str, Any] | None) -> float | None:
    if not recurring or str(recurring.get("currency")) != CURRENCY:
        return None
    amount = recurring.get("amount")
    return _eur(amount) if isinstance(amount, int | float) else None


async def subscription_rows(
    session: AsyncSession, accounts: Sequence[BillingAccount], *, now: datetime | None = None
) -> list[SubscriptionRow]:
    moment = now or datetime.now(UTC)
    ids = [a.workspace_id for a in accounts]
    names = await _organisation_names(session, ids)
    since: dict[uuid.UUID, datetime] = {}
    add_ons: dict[uuid.UUID, int] = {}
    if ids:
        since = dict(
            (
                await session.execute(
                    select(SubscriptionChange.workspace_id, func.max(SubscriptionChange.at))
                    .where(
                        SubscriptionChange.workspace_id.in_(ids),
                        SubscriptionChange.source == "plan",
                        SubscriptionChange.kind.in_(("new", "reactivation")),
                    )
                    .group_by(SubscriptionChange.workspace_id)
                )
            )
            .tuples()
            .all()
        )
        add_ons = dict(
            (
                await session.execute(
                    select(AgentEntitlement.workspace_id, func.count())
                    .where(
                        AgentEntitlement.workspace_id.in_(ids),
                        AgentEntitlement.origin == "purchase",
                        AgentEntitlement.status == "active",
                    )
                    .group_by(AgentEntitlement.workspace_id)
                )
            )
            .tuples()
            .all()
        )
    return [
        SubscriptionRow(
            organisation=OrganisationRef(id=a.workspace_id, name=names.get(a.workspace_id, "")),
            plan=a.plan,
            interval=a.interval,
            status=a.status,
            current_period_end=a.current_period_end,
            cancel_at_period_end=a.cancel_at_period_end,
            launch_offer_used=a.launch_offer_used,
            updated_at=a.updated_at,
            stripe_subscription_id=a.stripe_subscription_id,
            price_eur=_price(a.recurring),
            mrr_eur=_eur(mrr_of(a.recurring, moment)) if a.status in EARNING else 0.0,
            discount=_discount(a.recurring),
            since=since.get(a.workspace_id),
            add_ons=int(add_ons.get(a.workspace_id, 0)),
        )
        for a in accounts
    ]


# ── Invoices, payments, refunds, changes ─────────────────────────────────────


def invoices_query(
    *,
    organisation_id: uuid.UUID | None = None,
    organisation: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[BillingInvoice]]:
    statement = select(BillingInvoice).where(*_named(BillingInvoice.workspace_id, organisation))
    if organisation_id:
        statement = statement.where(BillingInvoice.workspace_id == organisation_id)
    if status:
        statement = statement.where(BillingInvoice.status == status)
    if since:
        statement = statement.where(BillingInvoice.issued_at >= since)
    if until:
        statement = statement.where(BillingInvoice.issued_at < until)
    return statement


def _line(said: dict[str, object]) -> InvoiceLine:
    amount = said.get("amount")
    start, end = said.get("start"), said.get("end")
    return InvoiceLine(
        description=str(said["description"]) if said.get("description") else None,
        amount=(_eur(amount) or 0.0) if isinstance(amount, int | float) else 0.0,
        proration=bool(said.get("proration")),
        start=datetime.fromisoformat(start) if isinstance(start, str) else None,
        end=datetime.fromisoformat(end) if isinstance(end, str) else None,
    )


async def invoice_rows(
    session: AsyncSession, invoices: Sequence[BillingInvoice]
) -> list[InvoiceRow]:
    names = await _organisation_names(session, (i.workspace_id for i in invoices))
    return [
        InvoiceRow(
            id=i.stripe_invoice_id,
            organisation=OrganisationRef(id=i.workspace_id, name=names.get(i.workspace_id, "")),
            number=i.number,
            status=i.status,
            billing_reason=i.billing_reason,
            currency=i.currency,
            subtotal=_eur(i.subtotal),
            discount=_eur(i.discount),
            tax=_eur(i.tax),
            total=_eur(i.total) or 0.0,
            amount_paid=_eur(i.amount_paid) or 0.0,
            amount_remaining=_eur(i.amount_remaining) or 0.0,
            proration=_eur(i.proration) or 0.0,
            period_start=i.period_start,
            period_end=i.period_end,
            issued_at=i.issued_at,
            paid_at=i.paid_at,
            attempts=i.attempts,
            hosted_url=i.hosted_url,
            lines=[_line(line) for line in i.lines],
        )
        for i in invoices
    ]


def payments_query(
    *,
    organisation_id: uuid.UUID | None = None,
    organisation: str | None = None,
    outcome: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[BillingPayment]]:
    statement = select(BillingPayment).where(*_named(BillingPayment.workspace_id, organisation))
    if organisation_id:
        statement = statement.where(BillingPayment.workspace_id == organisation_id)
    if outcome:
        statement = statement.where(BillingPayment.outcome == outcome)
    if since:
        statement = statement.where(BillingPayment.at >= since)
    if until:
        statement = statement.where(BillingPayment.at < until)
    return statement


async def payment_rows(
    session: AsyncSession, payments: Sequence[BillingPayment]
) -> list[PaymentRow]:
    names = await _organisation_names(session, (p.workspace_id for p in payments))
    return [
        PaymentRow(
            id=p.id,
            organisation=OrganisationRef(id=p.workspace_id, name=names.get(p.workspace_id, "")),
            outcome=p.outcome,
            amount=_eur(p.amount) or 0.0,
            currency=p.currency,
            invoice=p.stripe_invoice_id,
            attempt=p.attempt,
            next_attempt_at=p.next_attempt_at,
            at=p.at,
        )
        for p in payments
    ]


def refunds_query(
    *,
    organisation_id: uuid.UUID | None = None,
    organisation: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[BillingRefund]]:
    statement = select(BillingRefund).where(*_named(BillingRefund.workspace_id, organisation))
    if organisation_id:
        statement = statement.where(BillingRefund.workspace_id == organisation_id)
    if since:
        statement = statement.where(BillingRefund.at >= since)
    if until:
        statement = statement.where(BillingRefund.at < until)
    return statement


async def refund_rows(session: AsyncSession, refunds: Sequence[BillingRefund]) -> list[RefundRow]:
    names = await _organisation_names(session, (r.workspace_id for r in refunds))
    return [
        RefundRow(
            id=r.id,
            organisation=OrganisationRef(id=r.workspace_id, name=names.get(r.workspace_id, "")),
            charge=r.stripe_charge_id,
            invoice=r.stripe_invoice_id,
            amount=_eur(r.amount) or 0.0,
            charged=_eur(r.charged) or 0.0,
            currency=r.currency,
            reason=r.reason,
            at=r.at,
        )
        for r in refunds
    ]


def changes_query(
    *,
    organisation_id: uuid.UUID | None = None,
    organisation: str | None = None,
    kind: str | None = None,
    source: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[SubscriptionChange]]:
    statement = select(SubscriptionChange).where(
        *_named(SubscriptionChange.workspace_id, organisation)
    )
    if organisation_id:
        statement = statement.where(SubscriptionChange.workspace_id == organisation_id)
    if kind:
        statement = statement.where(SubscriptionChange.kind == kind)
    if source:
        statement = statement.where(SubscriptionChange.source == source)
    if since:
        statement = statement.where(SubscriptionChange.at >= since)
    if until:
        statement = statement.where(SubscriptionChange.at < until)
    return statement


async def change_rows(
    session: AsyncSession, changes: Sequence[SubscriptionChange]
) -> list[SubscriptionChangeRow]:
    names = await _organisation_names(session, (c.workspace_id for c in changes))
    return [
        SubscriptionChangeRow(
            id=c.id,
            organisation=OrganisationRef(id=c.workspace_id, name=names.get(c.workspace_id, "")),
            source=c.source,
            subscription=c.stripe_subscription_id,
            kind=c.kind,
            plan_before=c.plan_before,
            plan_after=c.plan_after,
            status_before=c.status_before,
            status_after=c.status_after,
            mrr_before_eur=_eur(c.mrr_before),
            mrr_after_eur=_eur(c.mrr_after),
            at=c.at,
        )
        for c in changes
    ]


async def subscription_detail(
    session: AsyncSession, workspace_id: uuid.UUID, *, now: datetime
) -> SubscriptionDetail | None:
    account = await session.scalar(
        select(BillingAccount).where(BillingAccount.workspace_id == workspace_id)
    )
    if account is None:
        workspace = await session.get(Workspace, workspace_id)
        if workspace is None:
            return None
        # Never subscribed: on Free, as its billing page says.
        account = BillingAccount(
            workspace_id=workspace_id,
            plan="free",
            cancel_at_period_end=False,
            launch_offer_used=False,
            updated_at=now,
        )
    [row] = await subscription_rows(session, [account], now=now)
    bought = (
        await session.scalars(
            select(AgentEntitlement)
            .where(
                AgentEntitlement.workspace_id == workspace_id,
                AgentEntitlement.origin == "purchase",
            )
            .order_by(AgentEntitlement.started_at.desc())
        )
    ).all()

    async def latest(query: Any, at: Any) -> Sequence[Any]:
        return (await session.scalars(query.order_by(at.desc()).limit(LATEST))).all()

    return SubscriptionDetail(
        subscription=row,
        add_ons=[
            SubscriptionAddOn(
                key=b.key,
                kind=b.kind,
                status=b.status,
                started_at=b.started_at,
                ended_at=b.ended_at,
                cancel_at_period_end=b.cancel_at_period_end,
                mrr_eur=_eur(mrr_of(b.recurring, now)) if b.status == "active" else 0.0,
            )
            for b in bought
        ],
        changes=await change_rows(
            session,
            (
                await session.scalars(
                    changes_query(organisation_id=workspace_id).order_by(
                        SubscriptionChange.at.desc()
                    )
                )
            ).all(),
        ),
        invoices=await invoice_rows(
            session,
            await latest(invoices_query(organisation_id=workspace_id), BillingInvoice.issued_at),
        ),
        payments=await payment_rows(
            session,
            await latest(payments_query(organisation_id=workspace_id), BillingPayment.at),
        ),
        refunds=await refund_rows(
            session, await latest(refunds_query(organisation_id=workspace_id), BillingRefund.at)
        ),
    )


# ── Finance ──────────────────────────────────────────────────────────────────


def _movement(changes: Sequence[SubscriptionChange], kinds: tuple[str, ...]) -> MrrMovement:
    """How the changes of these kinds moved the MRR: what came (new), went
    (churn), or the difference (up, down)."""
    found = [c for c in changes if c.kind in kinds]
    total, unknown = 0, 0
    for change in found:
        if change.kind in ("new", "reactivation"):
            moved = change.mrr_after
        elif change.kind == "churn":
            moved = change.mrr_before
        elif change.mrr_before is not None and change.mrr_after is not None:
            moved = abs(change.mrr_after - change.mrr_before)
        else:
            moved = None
        if moved is None:
            unknown += 1
        else:
            total += moved
    return MrrMovement(count=len(found), eur=_eur(total) or 0.0, unknown=unknown)


async def finance(session: AsyncSession, window: AdminWindow, *, now: datetime) -> FinanceOverview:
    since, until = window.start, window.end
    current = await revenue(session, now)
    # The MRR at the start: as kept at the end of the day before (the last
    # of that day's readings, leka.admin.overview.record_day). Set against
    # the MRR now with every movement since that midnight: only for a
    # period that ends now.
    midnight = since.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = await session.scalar(
        select(AdminDailyFigure.mrr).where(
            AdminDailyFigure.day == (midnight - timedelta(days=1)).date()
        )
    )
    mrr_start = float(start) if start is not None else None
    changes = (
        await session.scalars(
            select(SubscriptionChange).where(
                SubscriptionChange.at >= midnight,
                SubscriptionChange.at < until,
                _real(SubscriptionChange.workspace_id),
            )
        )
    ).all()
    within = [c for c in changes if c.at >= since]
    new = _movement(within, ("new",))
    back = _movement(within, ("reactivation",))
    up = _movement(within, ("upgrade",))
    down = _movement(within, ("downgrade",))
    gone = _movement(within, ("churn",))
    explained: float | None = None
    if mrr_start is not None and until >= now - timedelta(minutes=5):
        moved = [_movement(changes, (kind,)) for kind in ("new", "reactivation", "upgrade")]
        lost = [_movement(changes, (kind,)) for kind in ("downgrade", "churn")]
        explained = round(mrr_start + sum(m.eur for m in moved) - sum(m.eur for m in lost), 2)

    # By plan, and the agents bought alone together (each subscription
    # once): their MRR adds up to the MRR now.
    by_plan: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"subscriptions": 0, "mrr": 0.0, "unknown": 0}
    )
    plans = (
        await session.execute(
            select(BillingAccount.plan, BillingAccount.recurring).where(
                BillingAccount.stripe_subscription_id.is_not(None),
                BillingAccount.status.in_(EARNING),
                _real(BillingAccount.workspace_id),
            )
        )
    ).tuples()
    bought: dict[str, dict[str, Any] | None] = {}
    for subscription, recurring in (
        await session.execute(
            select(AgentEntitlement.stripe_subscription_id, AgentEntitlement.recurring).where(
                AgentEntitlement.origin == "purchase",
                AgentEntitlement.status == "active",
                AgentEntitlement.stripe_subscription_id.is_not(None),
                _real(AgentEntitlement.workspace_id),
            )
        )
    ).tuples():
        if subscription is not None and bought.get(subscription) is None:
            bought[subscription] = recurring
    for plan, recurring in [*plans, *(("add_ons", r) for r in bought.values())]:
        said = by_plan[plan]
        said["subscriptions"] += 1
        cents = mrr_of(recurring, now)
        if cents is None:
            said["unknown"] += 1
        else:
            said["mrr"] = round(float(said["mrr"]) + cents / 100, 2)

    other = 0

    def eur(rows: Sequence[tuple[str, int, int]]) -> tuple[int, int]:
        nonlocal other
        count, cents = 0, 0
        for currency, number, total in rows:
            if currency == CURRENCY:
                count, cents = count + int(number), cents + int(total or 0)
            else:
                other += int(number)
        return count, cents

    issued = eur(
        (
            await session.execute(
                select(BillingInvoice.currency, func.count(), func.sum(BillingInvoice.total))
                .where(
                    BillingInvoice.issued_at >= since,
                    BillingInvoice.issued_at < until,
                    BillingInvoice.status.in_(("open", "paid", "uncollectible")),
                    _real(BillingInvoice.workspace_id),
                )
                .group_by(BillingInvoice.currency)
            )
        )
        .tuples()
        .all()
    )
    prorated, taxed = (
        await session.execute(
            select(
                func.coalesce(func.sum(BillingInvoice.proration), 0),
                func.coalesce(func.sum(BillingInvoice.tax), 0),
            ).where(
                BillingInvoice.issued_at >= since,
                BillingInvoice.issued_at < until,
                BillingInvoice.currency == CURRENCY,
                BillingInvoice.status.in_(("open", "paid", "uncollectible")),
                _real(BillingInvoice.workspace_id),
            )
        )
    ).one()
    still_open = eur(
        (
            await session.execute(
                select(
                    BillingInvoice.currency,
                    func.count(),
                    func.sum(BillingInvoice.amount_remaining),
                )
                .where(BillingInvoice.status == "open", _real(BillingInvoice.workspace_id))
                .group_by(BillingInvoice.currency)
            )
        )
        .tuples()
        .all()
    )
    paid: dict[str, tuple[int, int]] = {}
    for outcome in ("succeeded", "failed"):
        paid[outcome] = eur(
            (
                await session.execute(
                    select(BillingPayment.currency, func.count(), func.sum(BillingPayment.amount))
                    .where(
                        BillingPayment.at >= since,
                        BillingPayment.at < until,
                        BillingPayment.outcome == outcome,
                        _real(BillingPayment.workspace_id),
                    )
                    .group_by(BillingPayment.currency)
                )
            )
            .tuples()
            .all()
        )
    refunded = eur(
        (
            await session.execute(
                select(BillingRefund.currency, func.count(), func.sum(BillingRefund.amount))
                .where(
                    BillingRefund.at >= since,
                    BillingRefund.at < until,
                    _real(BillingRefund.workspace_id),
                )
                .group_by(BillingRefund.currency)
            )
        )
        .tuples()
        .all()
    )

    events = dict(
        (
            await session.execute(
                select(StripeEvent.outcome, func.count())
                .where(StripeEvent.received_at >= since, StripeEvent.received_at < until)
                .group_by(StripeEvent.outcome)
            )
        )
        .tuples()
        .all()
    )
    failed = await session.scalar(select(func.count()).where(StripeEvent.outcome == "failed"))
    unlinked = await session.scalar(
        select(func.count()).where(
            StripeEvent.received_at >= since,
            StripeEvent.received_at < until,
            StripeEvent.for_workspace_id.is_(None),
        )
    )
    last = await session.scalar(select(func.max(StripeEvent.received_at)))

    return FinanceOverview(
        since=since,
        until=until,
        mrr=current.mrr,
        arr=round(current.mrr * 12, 2) if current.mrr is not None else None,
        mrr_start=mrr_start,
        subscriptions=current.counted,
        unknown_prices=current.unknown,
        trialing=current.trialing,
        new=new,
        reactivations=back,
        upgrades=up,
        downgrades=down,
        churn=gone,
        mrr_explained=explained,
        mrr_gap=round(current.mrr - explained, 2)
        if current.mrr is not None and explained is not None
        else None,
        by_plan=[
            PlanRevenue(plan=plan, **said)
            for plan, said in sorted(by_plan.items(), key=lambda item: -float(item[1]["mrr"]))
        ],
        invoiced=_eur(issued[1]) or 0.0,
        invoices=issued[0],
        invoiced_tax=_eur(int(taxed or 0)) or 0.0,
        prorations=_eur(int(prorated or 0)) or 0.0,
        open_invoices=still_open[0],
        open_amount=_eur(still_open[1]) or 0.0,
        payments_succeeded=paid["succeeded"][0],
        collected=_eur(paid["succeeded"][1]) or 0.0,
        payments_failed=paid["failed"][0],
        failed_amount=_eur(paid["failed"][1]) or 0.0,
        refunds=refunded[0],
        refunded=_eur(refunded[1]) or 0.0,
        net_collected=_eur(paid["succeeded"][1] - refunded[1]) or 0.0,
        other_currencies=other,
        events={str(k): int(v) for k, v in events.items()},
        failed_events=int(failed or 0),
        unlinked_events=int(unlinked or 0),
        last_event_at=last,
    )


__all__ = [
    "change_rows",
    "changes_query",
    "finance",
    "invoice_rows",
    "invoices_query",
    "payment_rows",
    "payments_query",
    "refund_rows",
    "refunds_query",
    "subscription_detail",
    "subscription_rows",
    "subscriptions_query",
]
