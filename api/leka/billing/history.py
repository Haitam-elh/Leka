"""What Stripe said of money, kept (LEKA-554): invoices, payments, refunds,
and each change of a subscription: from its verified events
(subscriptions.receive), or read again from its API (cli.py `history`).

Stripe is the source of truth: each row is what it last said, never a
figure of LEKA's own. An event older than the one a row was read from
changes nothing. No card data is ever kept.

Three things kept apart, never confused (docs/admin/indicateurs.md):

- recurring revenue: what the subscriptions bring in a month (the MRR),
  each at its price now, coupons taken off while they last, read from the
  subscriptions themselves (revenue.py), never from invoices;
- billing: what the invoices said was owed; a plan changed mid-period
  bills its prorations on the next one, never counted in the MRR;
- collection: what the payments took, less what refunds gave back.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing.models import (
    INVOICE_STATUSES,
    BillingInvoice,
    BillingPayment,
    BillingRefund,
    SubscriptionChange,
)
from leka.billing.revenue import monthly

CURRENCY = "eur"
# Earning: what counts in the MRR; a trial earns nothing yet.
EARNING = frozenset({"active", "past_due"})
ENDED = frozenset({"canceled", "unpaid", "incomplete_expired"})
PLAN_ORDER = ("free", "starter", "growth", "business", "enterprise")
LINES = 50


def _moment(seconds: object) -> datetime | None:
    return datetime.fromtimestamp(int(seconds), UTC) if isinstance(seconds, int | float) else None


def _iso(seconds: object) -> str | None:
    at = _moment(seconds)
    return at.isoformat() if at else None


def _int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _str(value: object, size: int) -> str | None:
    return str(value)[:size] if value else None


def mrr_of(recurring: Mapping[str, Any] | None, at: datetime) -> int | None:
    """A subscription's monthly recurring revenue in euro cents; None: not
    known (no fixed price, another currency)."""
    if not recurring or str(recurring.get("currency")) != CURRENCY:
        return None
    cents = monthly(recurring, at)
    return round(cents) if cents is not None else None


# ── Invoices, payments, refunds ──────────────────────────────────────────────


def _lines(invoice: Mapping[str, Any]) -> tuple[list[dict[str, object]], int]:
    """Each line as said (its description, amount, whether a proration),
    and what the prorations came to."""
    found: list[dict[str, object]] = []
    prorated = 0
    for line in ((invoice.get("lines") or {}).get("data") or [])[:LINES]:
        amount = _int(line.get("amount")) or 0
        proration = bool(line.get("proration"))
        if proration:
            prorated += amount
        period = line.get("period") or {}
        found.append(
            {
                "description": _str(line.get("description"), 300),
                "amount": amount,
                "proration": proration,
                "start": _iso(period.get("start")),
                "end": _iso(period.get("end")),
            }
        )
    return found, prorated


def _discount(invoice: Mapping[str, Any]) -> int | None:
    amounts = invoice.get("total_discount_amounts")
    if isinstance(amounts, list):
        return sum(_int(a.get("amount")) or 0 for a in amounts if isinstance(a, Mapping))
    return None


async def keep_invoice(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    invoice: Mapping[str, Any],
    *,
    said_at: datetime,
    said_by: str,
) -> bool:
    """An invoice as Stripe says it now; an older word changes nothing.
    True: kept."""
    invoice_id = str(invoice.get("id") or "")
    status = str(invoice.get("status") or "")
    if not invoice_id or status not in INVOICE_STATUSES or not invoice.get("currency"):
        return False
    lines, prorated = _lines(invoice)
    transitions = invoice.get("status_transitions") or {}
    row = await session.scalar(
        select(BillingInvoice).where(BillingInvoice.stripe_invoice_id == invoice_id)
    )
    if row is not None and row.said_at > said_at:
        return False
    values: dict[str, Any] = {
        "stripe_subscription_id": _str(invoice.get("subscription"), 100),
        "number": _str(invoice.get("number"), 60),
        "status": status,
        "billing_reason": _str(invoice.get("billing_reason"), 40),
        "currency": str(invoice["currency"]).lower()[:3],
        "subtotal": _int(invoice.get("subtotal")),
        "discount": _discount(invoice),
        "tax": _int(invoice.get("tax")),
        "total": _int(invoice.get("total")) or 0,
        "amount_paid": _int(invoice.get("amount_paid")) or 0,
        "amount_due": _int(invoice.get("amount_due")) or 0,
        "amount_remaining": _int(invoice.get("amount_remaining")) or 0,
        "proration": prorated,
        "period_start": _moment(invoice.get("period_start")),
        "period_end": _moment(invoice.get("period_end")),
        "issued_at": _moment(invoice.get("created")) or said_at,
        "paid_at": _moment(transitions.get("paid_at")),
        "attempts": _int(invoice.get("attempt_count")) or 0,
        "hosted_url": _str(invoice.get("hosted_invoice_url"), 500),
        "lines": lines,
        "said_at": said_at,
        "said_by": said_by[:100],
    }
    if row is None:
        session.add(
            BillingInvoice(
                workspace_id=workspace_id, id=uuid.uuid4(), stripe_invoice_id=invoice_id, **values
            )
        )
    else:
        for key, value in values.items():
            setattr(row, key, value)
    if status == "paid" and values["amount_paid"] > 0:
        await keep_payment(
            session,
            workspace_id,
            reference=f"{invoice_id}:paid",
            invoice=invoice,
            outcome="succeeded",
            amount=values["amount_paid"],
            at=values["paid_at"] or said_at,
        )
    return True


async def keep_payment(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    reference: str,
    invoice: Mapping[str, Any],
    outcome: str,
    amount: int,
    at: datetime,
) -> bool:
    """A payment taken (one per invoice paid) or an attempt that failed (one
    per event): written once."""
    written = await session.scalar(
        insert(BillingPayment)
        .values(
            workspace_id=workspace_id,
            id=uuid.uuid4(),
            reference=reference[:120],
            stripe_invoice_id=_str(invoice.get("id"), 100),
            stripe_charge_id=_str(invoice.get("charge"), 100),
            outcome=outcome,
            amount=amount,
            currency=str(invoice.get("currency") or CURRENCY).lower()[:3],
            attempt=_int(invoice.get("attempt_count")),
            next_attempt_at=_moment(invoice.get("next_payment_attempt")),
            at=at,
        )
        .on_conflict_do_nothing(constraint="uq_billing_payments_reference")
        .returning(BillingPayment.id)
    )
    return written is not None


async def keep_failed_payment(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    invoice: Mapping[str, Any],
    *,
    event_id: str,
    at: datetime,
) -> bool:
    return await keep_payment(
        session,
        workspace_id,
        reference=event_id,
        invoice=invoice,
        outcome="failed",
        amount=_int(invoice.get("amount_due")) or 0,
        at=at,
    )


async def keep_refund(
    session: AsyncSession, workspace_id: uuid.UUID, charge: Mapping[str, Any], *, said_at: datetime
) -> bool:
    """What a charge gave back, every refund of it together; an older word
    changes nothing."""
    charge_id = str(charge.get("id") or "")
    refunded = _int(charge.get("amount_refunded"))
    if not charge_id or refunded is None or not charge.get("currency"):
        return False
    refunds = (charge.get("refunds") or {}).get("data") or []
    latest = refunds[0] if refunds and isinstance(refunds[0], Mapping) else {}
    row = await session.scalar(
        select(BillingRefund).where(BillingRefund.stripe_charge_id == charge_id)
    )
    if row is not None and row.said_at > said_at:
        return False
    values: dict[str, Any] = {
        "stripe_invoice_id": _str(charge.get("invoice"), 100),
        "amount": refunded,
        "charged": _int(charge.get("amount")) or 0,
        "currency": str(charge["currency"]).lower()[:3],
        "reason": _str(latest.get("reason"), 60),
        "at": _moment(latest.get("created")) or said_at,
        "said_at": said_at,
    }
    if row is None:
        session.add(
            BillingRefund(
                workspace_id=workspace_id, id=uuid.uuid4(), stripe_charge_id=charge_id, **values
            )
        )
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return True


# ── A subscription changed ───────────────────────────────────────────────────


@dataclass(frozen=True)
class State:
    """A subscription as it stood: its plan (or add-on), status, interval,
    renewal, and its MRR (cents; 0 when it earns nothing; None: not known)."""

    plan: str | None
    status: str | None
    interval: str | None
    cancel_at_period_end: bool
    mrr: int | None

    @property
    def earning(self) -> bool:
        return self.status in EARNING


def _rank(plan: str | None) -> int:
    return PLAN_ORDER.index(plan) if plan in PLAN_ORDER else -1


def kind_of(before: State, after: State) -> str | None:
    """What a change was (docs/admin/indicateurs.md): a trial started; new,
    or back after having ended; up or down (by its MRR, else by its plan);
    its interval; its renewal stopped or resumed; ended. None: nothing that
    counts."""
    if after.status == "trialing" and before.status != "trialing":
        return "trial"
    if not before.earning and after.earning:
        return "reactivation" if before.status in ENDED else "new"
    if before.earning and not after.earning:
        return "churn"
    if not (before.earning and after.earning):
        return None
    if before.mrr is not None and after.mrr is not None and before.mrr != after.mrr:
        return "upgrade" if after.mrr > before.mrr else "downgrade"
    if before.plan != after.plan and _rank(before.plan) != _rank(after.plan):
        return "upgrade" if _rank(after.plan) > _rank(before.plan) else "downgrade"
    if before.interval != after.interval:
        return "interval"
    if before.cancel_at_period_end != after.cancel_at_period_end:
        return "renewal_off" if after.cancel_at_period_end else "renewal_on"
    return None


async def keep_change(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    event_id: str,
    source: str,
    subscription_id: str,
    before: State,
    after: State,
    at: datetime,
) -> str | None:
    """The change an event made, written once; none when nothing counts."""
    kind = kind_of(before, after)
    if kind is None or not subscription_id:
        return None
    await session.execute(
        insert(SubscriptionChange)
        .values(
            workspace_id=workspace_id,
            id=uuid.uuid4(),
            event_id=event_id[:100],
            source=source,
            stripe_subscription_id=subscription_id[:100],
            kind=kind,
            plan_before=before.plan,
            plan_after=after.plan,
            status_before=before.status,
            status_after=after.status,
            interval_after=after.interval,
            mrr_before=before.mrr if before.earning else 0,
            mrr_after=after.mrr if after.earning else 0,
            at=at,
        )
        .on_conflict_do_nothing(constraint="uq_billing_subscription_changes_event")
    )
    return kind


__all__ = [
    "EARNING",
    "State",
    "keep_change",
    "keep_failed_payment",
    "keep_invoice",
    "keep_payment",
    "keep_refund",
    "kind_of",
    "mrr_of",
]
