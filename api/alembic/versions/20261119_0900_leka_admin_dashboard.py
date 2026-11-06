"""What a subscription brings in, kept; the MRR of each day.

Revision ID: 5e14651feb40
Revises: 7c3e9a1b5d24
Created: 2026-11-06

LEKA-548.
- `billing_accounts.recurring`, `agent_entitlements.recurring`: the
  subscription's recurring price, as Stripe last said it (leka/billing/
  revenue.py). Null until an event of the subscription says it, or
  `python -m leka.billing.cli amounts` reads it from Stripe.
- `admin_daily_figures`: the MRR as it stood each day, written by the
  activity sweep, so that its evolution can be drawn.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5e14651feb40"
down_revision: str | None = "7c3e9a1b5d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_accounts",
        sa.Column("recurring", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "agent_entitlements",
        sa.Column("recurring", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "admin_daily_figures",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("mrr", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("subscriptions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unknown", sa.Integer(), server_default="0", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_daily_figures")),
        sa.UniqueConstraint("day", name="uq_admin_daily_figures_day"),
    )


def downgrade() -> None:
    op.drop_table("admin_daily_figures")
    op.drop_column("agent_entitlements", "recurring")
    op.drop_column("billing_accounts", "recurring")
