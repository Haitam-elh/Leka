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


class AddOnCheckout(Base, WorkspaceScopedMixin):
    __tablename__ = "add_on_checkouts"
    __table_args__ = (
        UniqueConstraint("stripe_session_id", name="uq_add_on_checkouts_session"),
        CheckConstraint("kind IN ('agent', 'bundle', 'agents')", name="kind"),
        CheckConstraint("status IN ('open', 'paid', 'expired')", name="status"),
    )

    stripe_session_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # « agents »: several bought together (LEKA-458), their keys in `key`.
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    key: Mapped[str] = mapped_column(String(400), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Opened from an intention's decision: launched once paid.
    intention_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    launch: Mapped[list[object]] = mapped_column(JSONB, nullable=False, server_default="[]")
