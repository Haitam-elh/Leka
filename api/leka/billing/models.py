"""Tables owned by the billing module (LEKA-431).

`billing_accounts`: a workspace's subscription as Stripe last said it — its
customer, its subscription, the plan and interval it pays for, where it
stands, until when, and whether it has had the launch offer. Written only
from verified Stripe events and the checkout LEKA opened.

`stripe_events`: every Stripe event received, once — its id unique, so a
delivery repeated, or replayed, is never applied twice. LEKA's own record:
which workspace it was about is `for_workspace_id`, not the isolation
column (an event can be about no workspace LEKA knows).

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
