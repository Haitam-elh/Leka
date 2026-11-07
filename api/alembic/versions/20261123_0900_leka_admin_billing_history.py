"""What Stripe said of money, kept.

Revision ID: 658e6460a4b5
Revises: 9a4f12e2702e
Created: 2026-11-07

LEKA-554. Read from Stripe's verified events (and its API, read again with
`python -m leka.billing.cli history`), Stripe the source of truth; no card
data, ever. Each deleted with its workspace.
- `billing_invoices`: each invoice as Stripe last said it, its amounts in
  cents, its discount, tax and prorations apart.
- `billing_payments`: a payment taken (one per invoice paid) or an attempt
  that failed.
- `billing_refunds`: what a charge gave back.
- `billing_subscription_changes`: each change of a subscription, a plan's or
  an add-on's, its monthly recurring revenue before and after.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "658e6460a4b5"
down_revision: str | None = "9a4f12e2702e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base(table: str) -> list[sa.SchemaItem]:
    return [
        sa.Column("workspace_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{table}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    op.create_table(
        "billing_invoices",
        sa.Column("stripe_invoice_id", sa.String(length=100), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=100), nullable=True),
        sa.Column("number", sa.String(length=60), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("billing_reason", sa.String(length=40), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Integer(), nullable=True),
        sa.Column("discount", sa.Integer(), nullable=True),
        sa.Column("tax", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("amount_paid", sa.Integer(), nullable=False),
        sa.Column("amount_due", sa.Integer(), nullable=False),
        sa.Column("amount_remaining", sa.Integer(), nullable=False),
        sa.Column("proration", sa.Integer(), server_default="0", nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("hosted_url", sa.String(length=500), nullable=True),
        sa.Column(
            "lines", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("said_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("said_by", sa.String(length=100), nullable=False),
        *_base("billing_invoices"),
        sa.UniqueConstraint("stripe_invoice_id", name="uq_billing_invoices_invoice"),
        sa.CheckConstraint(
            "status IN ('draft', 'open', 'paid', 'uncollectible', 'void')",
            name=op.f("ck_billing_invoices_status"),
        ),
    )
    op.create_index(op.f("ix_billing_invoices_workspace_id"), "billing_invoices", ["workspace_id"])
    op.create_index("ix_billing_invoices_issued", "billing_invoices", ["issued_at"])
    op.create_index(
        "ix_billing_invoices_workspace_issued", "billing_invoices", ["workspace_id", "issued_at"]
    )

    op.create_table(
        "billing_payments",
        sa.Column("reference", sa.String(length=120), nullable=False),
        sa.Column("stripe_invoice_id", sa.String(length=100), nullable=True),
        sa.Column("stripe_charge_id", sa.String(length=100), nullable=True),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        *_base("billing_payments"),
        sa.UniqueConstraint("reference", name="uq_billing_payments_reference"),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'failed')", name=op.f("ck_billing_payments_outcome")
        ),
    )
    op.create_index(op.f("ix_billing_payments_workspace_id"), "billing_payments", ["workspace_id"])
    op.create_index("ix_billing_payments_at", "billing_payments", ["at"])
    op.create_index("ix_billing_payments_workspace_at", "billing_payments", ["workspace_id", "at"])

    op.create_table(
        "billing_refunds",
        sa.Column("stripe_charge_id", sa.String(length=100), nullable=False),
        sa.Column("stripe_invoice_id", sa.String(length=100), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("charged", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.String(length=60), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("said_at", sa.DateTime(timezone=True), nullable=False),
        *_base("billing_refunds"),
        sa.UniqueConstraint("stripe_charge_id", name="uq_billing_refunds_charge"),
    )
    op.create_index(op.f("ix_billing_refunds_workspace_id"), "billing_refunds", ["workspace_id"])
    op.create_index("ix_billing_refunds_at", "billing_refunds", ["at"])

    op.create_table(
        "billing_subscription_changes",
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("plan_before", sa.String(length=100), nullable=True),
        sa.Column("plan_after", sa.String(length=100), nullable=True),
        sa.Column("status_before", sa.String(length=30), nullable=True),
        sa.Column("status_after", sa.String(length=30), nullable=True),
        sa.Column("interval_after", sa.String(length=10), nullable=True),
        sa.Column("mrr_before", sa.Integer(), nullable=True),
        sa.Column("mrr_after", sa.Integer(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        *_base("billing_subscription_changes"),
        sa.UniqueConstraint(
            "event_id", "stripe_subscription_id", name="uq_billing_subscription_changes_event"
        ),
        sa.CheckConstraint(
            "kind IN ('trial', 'new', 'reactivation', 'upgrade', 'downgrade', 'interval',"
            " 'renewal_off', 'renewal_on', 'churn')",
            name=op.f("ck_billing_subscription_changes_kind"),
        ),
        sa.CheckConstraint(
            "source IN ('plan', 'add_on')", name=op.f("ck_billing_subscription_changes_source")
        ),
    )
    op.create_index(
        op.f("ix_billing_subscription_changes_workspace_id"),
        "billing_subscription_changes",
        ["workspace_id"],
    )
    op.create_index("ix_billing_subscription_changes_at", "billing_subscription_changes", ["at"])
    op.create_index(
        "ix_billing_subscription_changes_workspace_at",
        "billing_subscription_changes",
        ["workspace_id", "at"],
    )


def downgrade() -> None:
    for table in (
        "billing_subscription_changes",
        "billing_refunds",
        "billing_payments",
        "billing_invoices",
    ):
        op.drop_table(table)
