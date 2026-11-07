"""The AI credits' ledger.

Revision ID: 9a4f12e2702e
Revises: 3643a84285a4
Created: 2026-11-07

LEKA-553. `credit_transactions`: every movement of a workspace's AI
credits — a month's grant by its plan or a pack, a consumption, a refund or
an adjustment by LEKA's team, a month's expiration — each written once
(`reference` unique in the workspace) and never changed; deleted with its
workspace. The ledger's lines are written by the hourly sweep
(leka.metering.ledger), the whole history of each workspace on its first
pass: nothing is copied here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9a4f12e2702e"
down_revision: str | None = "3643a84285a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "credit_transactions"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("credits", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=False),
        sa.Column("execution", sa.String(length=160), nullable=True),
        sa.Column("subject", sa.String(length=100), nullable=True),
        sa.Column("by_whom", sa.String(length=320), nullable=True),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
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
            name=op.f("fk_credit_transactions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_transactions")),
        sa.UniqueConstraint("workspace_id", "reference", name="uq_credit_transactions_reference"),
        sa.CheckConstraint(
            "kind IN ('grant', 'consumption', 'refund', 'adjustment', 'expiration')",
            name=op.f("ck_credit_transactions_kind"),
        ),
        sa.CheckConstraint(
            "kind NOT IN ('refund', 'adjustment') OR (by_whom IS NOT NULL AND reason IS NOT NULL)",
            name=op.f("ck_credit_transactions_manual_said"),
        ),
        sa.CheckConstraint(
            "kind <> 'refund' OR credits > 0", name=op.f("ck_credit_transactions_refund_gives")
        ),
    )
    op.create_index(op.f("ix_credit_transactions_workspace_id"), TABLE, ["workspace_id"])
    op.create_index("ix_credit_transactions_workspace_period", TABLE, ["workspace_id", "period"])
    op.create_index("ix_credit_transactions_workspace_at", TABLE, ["workspace_id", "at"])
    op.create_index("ix_credit_transactions_execution", TABLE, ["workspace_id", "execution"])

    # A movement is never changed: a correction is a movement of its own. Its
    # workspace may be erased, and its ledger with it.
    op.execute(
        """
        CREATE FUNCTION credit_transactions_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'credit_transactions is append-only: a movement is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER credit_transactions_append_only
        BEFORE UPDATE ON credit_transactions
        FOR EACH ROW EXECUTE FUNCTION credit_transactions_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER credit_transactions_append_only ON credit_transactions")
    op.execute("DROP FUNCTION credit_transactions_append_only()")
    op.drop_table(TABLE)
