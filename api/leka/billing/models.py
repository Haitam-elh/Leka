"""Tables owned by the billing module (LEKA-431).

`site_events`: what visitors of the pricing page chose and clicked — a plan
selected, the billing interval switched, a call to action — for LEKA's own
analytics. The product's, no customer's: no workspace, no person, no
address; what was clicked, on which plan and interval, when.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

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
