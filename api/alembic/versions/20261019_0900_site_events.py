"""Site events: what visitors of the pricing page chose and clicked.

Revision ID: 6b1d8e3f2a94
Revises: 0a074280012e
Created: 2026-10-19

LEKA-431. One row per thing a visitor of leka-core.com's pricing page did —
the page viewed, a billing interval or a plan chosen, a call to action, an
Enterprise meeting booked or the contact form opened — with the plan, the
interval and the language. LEKA's own analytics: no workspace, no person,
no address.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6b1d8e3f2a94"
down_revision: str | None = "0a074280012e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENTS = (
    "page_viewed",
    "interval_selected",
    "plan_selected",
    "cta_clicked",
    "enterprise_booking_clicked",
    "enterprise_contact_clicked",
)


def upgrade() -> None:
    op.create_table(
        "site_events",
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("page", sa.String(length=40), nullable=False),
        sa.Column("plan", sa.String(length=20), nullable=True),
        sa.Column("interval", sa.String(length=10), nullable=True),
        sa.Column("language", sa.String(length=5), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event IN (" + ", ".join(f"'{e}'" for e in EVENTS) + ")",
            name=op.f("ck_site_events_event"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_events")),
    )
    op.create_index("ix_site_events_event_at", "site_events", ["event", "at"])


def downgrade() -> None:
    op.drop_index("ix_site_events_event_at", table_name="site_events")
    op.drop_table("site_events")
