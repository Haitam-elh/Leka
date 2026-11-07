"""Tables owned by the billing module (LEKA-431).

`billing_accounts`: a workspace's subscription as Stripe last said it — its
customer, its subscription, the plan and interval it pays for, where it
stands, until when, and whether it has had the launch offer. Written only
from verified Stripe events and the checkout LEKA opened.

`stripe_events`: every Stripe event received, once — its id unique, so a
delivery repeated, or replayed, is never applied twice. LEKA's own record:
which workspace it was about is `for_workspace_id`, not the isolation
column (an event can be about no workspace LEKA knows).

`agent_entitlements` (2026-10-14): the agents a workspace may run — one
bought alone, a bundle, or every one LEKA granted it (its team's, for
tests). Ended, never deleted: who had what, when, is kept.

`add_on_checkouts`: a Checkout LEKA opened for an agent or a bundle — and,
when it was opened from an intention's decision, the agents to launch once
it is paid.

`site_events`: what visitors of the pricing page chose and clicked — a plan
selected, the billing interval switched, a call to action — for LEKA's own
analytics. The product's, no customer's: no workspace, no person, no
address; what was clicked, on which plan and interval, when.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin

# What the pricing page records.
EVENTS = (
    "page_viewed",
    "interval_selected",
    "plan_selected",
    "cta_clicked",
    "enterprise_booking_clicked",
    "enterprise_contact_clicked",
)


class SiteEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "site_events"
    __table_args__ = (
        CheckConstraint("event IN (" + ", ".join(f"'{e}'" for e in EVENTS) + ")", name="event"),
        Index("ix_site_events_event_at", "event", "at"),
    )

    event: Mapped[str] = mapped_column(String(40), nullable=False)
    page: Mapped[str] = mapped_column(String(40), nullable=False)
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    interval: Mapped[str | None] = mapped_column(String(10), nullable=True)
    language: Mapped[str | None] = mapped_column(String(5), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BillingAccount(Base, WorkspaceScopedMixin):
    __tablename__ = "billing_accounts"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_billing_accounts_workspace"),
        UniqueConstraint("stripe_customer_id", name="uq_billing_accounts_customer"),
    )

    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # What it pays for; free when nothing.
    plan: Mapped[str] = mapped_column(String(20), nullable=False, server_default="free")
    interval: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Stripe's word: active, trialing, past_due, unpaid, canceled, incomplete…
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Taken once: a workspace that ever subscribed has had its chance.
    launch_offer_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # The last invoice's outcome: paid, payment_failed.
    last_invoice: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # When Stripe made the last subscription event applied: an older one,
    # delivered late, never undoes it.
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The subscription's recurring price, as Stripe last said it (LEKA-548,
    # leka/billing/revenue.py); null while it pays nothing or is not known.
    recurring: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class StripeEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "stripe_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_stripe_events_event"),
        CheckConstraint("outcome IN ('applied', 'ignored', 'failed')", name="outcome"),
    )

    event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    for_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentEntitlement(Base, WorkspaceScopedMixin):
    __tablename__ = "agent_entitlements"
    __table_args__ = (
        CheckConstraint("kind IN ('agent', 'bundle', 'all')", name="kind"),
        CheckConstraint("origin IN ('purchase', 'grant')", name="origin"),
        CheckConstraint("status IN ('active', 'ended')", name="status"),
        Index("ix_agent_entitlements_workspace_status", "workspace_id", "status"),
    )

    # An agent's key, a bundle's, or « * » for every one.
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Its subscription's renewal, as Stripe last said it (LEKA-474): cancelled
    # at its period's end — kept until then — or renewed.
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Who: a person's id, an operator's name, Stripe.
    by_whom: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A purchase's subscription's recurring price (LEKA-548): the same on
    # every right one subscription bought, counted once.
    recurring: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class AddOnCheckout(Base, WorkspaceScopedMixin):
    __tablename__ = "add_on_checkouts"
    __table_args__ = (
        UniqueConstraint("stripe_session_id", name="uq_add_on_checkouts_session"),
        CheckConstraint("kind IN ('agent', 'bundle', 'agents', 'bundles')", name="kind"),
        CheckConstraint("status IN ('open', 'paid', 'expired')", name="status"),
    )

    stripe_session_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # « agents », « bundles »: several bought together (LEKA-458, LEKA-500),
    # their keys in `key`.
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    key: Mapped[str] = mapped_column(String(400), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Opened from an intention's decision: launched once paid.
    intention_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    launch: Mapped[list[object]] = mapped_column(JSONB, nullable=False, server_default="[]")


# ── What Stripe said of money, kept (LEKA-554) ───────────────────────────────
#
# Stripe is the source of truth: each row is what one of its events (or a
# reading of its API) said, the latest kept. No card data is ever kept:
# not a number, a brand, nor the last four digits.

INVOICE_STATUSES = ("draft", "open", "paid", "uncollectible", "void")
CHANGE_KINDS = (
    "trial",
    "new",
    "reactivation",
    "upgrade",
    "downgrade",
    "interval",
    "renewal_off",
    "renewal_on",
    "churn",
)


class BillingInvoice(Base, WorkspaceScopedMixin):
    """An invoice of Stripe's, as it last said it: what was billed, paid and
    due, in cents, excluding nothing; its discount and tax said apart."""

    __tablename__ = "billing_invoices"
    __table_args__ = (
        UniqueConstraint("stripe_invoice_id", name="uq_billing_invoices_invoice"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in INVOICE_STATUSES) + ")", name="status"
        ),
        Index("ix_billing_invoices_issued", "issued_at"),
        Index("ix_billing_invoices_workspace_issued", "workspace_id", "issued_at"),
    )

    stripe_invoice_id: Mapped[str] = mapped_column(String(100), nullable=False)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # subscription_create, subscription_cycle, subscription_update (a plan
    # changed: its prorations), manual…
    billing_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tax: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paid: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_due: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    # Its share of prorations: what a plan changed mid-period billed.
    proration: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Stripe's page of the invoice: what a person opens to see it.
    hosted_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lines: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # When Stripe said it: an event older than the one kept changes nothing.
    said_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The event it was last read from, or « sync » (the API, read again).
    said_by: Mapped[str] = mapped_column(String(100), nullable=False)


class BillingPayment(Base, WorkspaceScopedMixin):
    """A payment Stripe took, or tried and could not: an invoice paid, or one
    of its attempts that failed. Money collected, never revenue."""

    __tablename__ = "billing_payments"
    __table_args__ = (
        UniqueConstraint("reference", name="uq_billing_payments_reference"),
        CheckConstraint("outcome IN ('succeeded', 'failed')", name="outcome"),
        Index("ix_billing_payments_at", "at"),
        Index("ix_billing_payments_workspace_at", "workspace_id", "at"),
    )

    # The invoice paid (one success each), or the event of a failed attempt.
    reference: Mapped[str] = mapped_column(String(120), nullable=False)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stripe_charge_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BillingRefund(Base, WorkspaceScopedMixin):
    """What a charge gave back, as Stripe last said it: every refund of it
    together (Stripe's `amount_refunded`)."""

    __tablename__ = "billing_refunds"
    __table_args__ = (
        UniqueConstraint("stripe_charge_id", name="uq_billing_refunds_charge"),
        Index("ix_billing_refunds_at", "at"),
    )

    stripe_charge_id: Mapped[str] = mapped_column(String(100), nullable=False)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    charged: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    said_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SubscriptionChange(Base, WorkspaceScopedMixin):
    """One change of a subscription (a plan's or an add-on's) as Stripe's
    events applied it: what it was, what it became, and its monthly
    recurring revenue before and after (cents, EUR, excluding VAT, coupons
    applied): the movements of the MRR, explained."""

    __tablename__ = "billing_subscription_changes"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "stripe_subscription_id", name="uq_billing_subscription_changes_event"
        ),
        CheckConstraint("kind IN (" + ", ".join(f"'{k}'" for k in CHANGE_KINDS) + ")", name="kind"),
        CheckConstraint("source IN ('plan', 'add_on')", name="source"),
        Index("ix_billing_subscription_changes_at", "at"),
        Index("ix_billing_subscription_changes_workspace_at", "workspace_id", "at"),
    )

    event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    stripe_subscription_id: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    plan_before: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plan_after: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status_before: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status_after: Mapped[str | None] = mapped_column(String(30), nullable=True)
    interval_after: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Null: not known (a price Stripe did not say as one fixed amount).
    mrr_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mrr_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
