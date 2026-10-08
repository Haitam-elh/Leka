"""Intention verifications: what was expected of an action, and whether it came.

Revision ID: 2d9f6b3e8a51
Revises: 4c8e2b7f9d13
Created: 2026-10-09

LEKA-392. A plan's expectations, set before it runs; once it succeeded, its
verification (`intention_verifications`): what was observed of each, read
again until met or the deadline, the verdict — succeeded, partial, failed —
and what the company's context was told.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2d9f6b3e8a51"
down_revision: str | None = "4c8e2b7f9d13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intention_verifications",
        sa.Column("intention_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "expectations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "results", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("observe_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("concluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("concluded_by", sa.UUID(), nullable=True),
        sa.Column(
            "context_update",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
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
        sa.CheckConstraint(
            "status IN ('verifying', 'succeeded', 'partial', 'failed')",
            name=op.f("ck_intention_verifications_status"),
        ),
        sa.ForeignKeyConstraint(
            ["concluded_by"],
            ["users.id"],
            name=op.f("fk_intention_verifications_concluded_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            name="fk_intention_verifications_intention",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "plan_id"],
            ["intention_plans.workspace_id", "intention_plans.id"],
            name="fk_intention_verifications_plan",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_intention_verifications_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intention_verifications")),
        sa.UniqueConstraint("plan_id", name="uq_intention_verifications_plan"),
    )
    op.create_index(
        "ix_intention_verifications_due",
        "intention_verifications",
        ["status", "observe_after"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intention_verifications_workspace_id"),
        "intention_verifications",
        ["workspace_id"],
        unique=False,
    )
    op.add_column(
        "intention_plans",
        sa.Column(
            "expectations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("intention_plans", "expectations")
    op.drop_index(
        op.f("ix_intention_verifications_workspace_id"), table_name="intention_verifications"
    )
    op.drop_index("ix_intention_verifications_due", table_name="intention_verifications")
    op.drop_table("intention_verifications")
