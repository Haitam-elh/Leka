"""Billing accounts and Stripe events: a workspace's subscription, and every
event Stripe sent, once.

Revision ID: 7c2e9f4a1b85
Revises: 6b1d8e3f2a94
Created: 2026-10-19

LEKA-431. `billing_accounts`: one per workspace — its Stripe customer and
subscription, the plan and interval paid for, where it stands, until when,
whether the launch offer was taken, the last invoice's outcome, when the
last subscription event applied was made. `stripe_events`: every event
received, its id unique — a repeated delivery is never applied twice — and
what came of it; the workspace it was about as `for_workspace_id`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7c2e9f4a1b85"
down_revision: str | None = "6b1d8e3f2a94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "billing_accounts",
        sa.Column("stripe_customer_id", sa.String(length=100), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=100), nullable=True),
        sa.Column("plan", sa.String(length=20), server_default="free", nullable=False),
        sa.Column("interval", sa.String(length=10), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "launch_offer_used", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("last_invoice", sa.String(length=30), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_billing_accounts_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_accounts")),
        sa.UniqueConstraint("workspace_id", name="uq_billing_accounts_workspace"),
        sa.UniqueConstraint("stripe_customer_id", name="uq_billing_accounts_customer"),
    )
    op.create_index(
        op.f("ix_billing_accounts_workspace_id"), "billing_accounts", ["workspace_id"], unique=False
    )
    op.create_table(
        "stripe_events",
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("for_workspace_id", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "outcome IN ('applied', 'ignored', 'failed')", name=op.f("ck_stripe_events_outcome")
        ),
        sa.ForeignKeyConstraint(
            ["for_workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_stripe_events_for_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stripe_events")),
        sa.UniqueConstraint("event_id", name="uq_stripe_events_event"),
    )
    op.create_index(
        op.f("ix_stripe_events_for_workspace_id"), "stripe_events", ["for_workspace_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_stripe_events_for_workspace_id"), table_name="stripe_events")
    op.drop_table("stripe_events")
    op.drop_index(op.f("ix_billing_accounts_workspace_id"), table_name="billing_accounts")
    op.drop_table("billing_accounts")
