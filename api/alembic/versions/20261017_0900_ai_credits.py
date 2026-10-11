"""AI credits: a workspace's plan and its history, the packs added to a
month, and the warnings told.

Revision ID: b2aa4e15dd98
Revises: b939e6b4cd71
Created: 2026-10-17

LEKA-430. `workspace_plans`: every plan a workspace was put on, from when,
by whom at LEKA, why — its plan is the latest; none, Free. `credit_packs`:
credits added to a month, gone when it ends. `credit_warnings`: a share of
a month's credits told to its owners and admins — once.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2aa4e15dd98"
down_revision: str | None = "b939e6b4cd71"
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
        "workspace_plans",
        sa.Column("plan", sa.String(length=12), nullable=False),
        sa.Column("monthly_credits", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("set_by", sa.String(length=100), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        *_base("workspace_plans"),
        sa.CheckConstraint(
            "plan IN ('free', 'starter', 'growth', 'business', 'enterprise')",
            name=op.f("ck_workspace_plans_plan"),
        ),
        sa.CheckConstraint(
            "monthly_credits IS NULL OR monthly_credits >= 0",
            name=op.f("ck_workspace_plans_credits"),
        ),
    )
    op.create_index(op.f("ix_workspace_plans_workspace_id"), "workspace_plans", ["workspace_id"])
    op.create_index("ix_workspace_plans_workspace_at", "workspace_plans", ["workspace_id", "at"])

    op.create_table(
        "credit_packs",
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("granted_by", sa.String(length=100), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        *_base("credit_packs"),
        sa.CheckConstraint("credits > 0", name=op.f("ck_credit_packs_credits")),
    )
    op.create_index(op.f("ix_credit_packs_workspace_id"), "credit_packs", ["workspace_id"])
    op.create_index("ix_credit_packs_workspace_period", "credit_packs", ["workspace_id", "period"])

    op.create_table(
        "credit_warnings",
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("used", sa.Float(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        *_base("credit_warnings"),
        sa.UniqueConstraint("workspace_id", "period", "threshold", name="uq_credit_warnings_once"),
    )
    op.create_index(op.f("ix_credit_warnings_workspace_id"), "credit_warnings", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("credit_warnings")
    op.drop_table("credit_packs")
    op.drop_table("workspace_plans")
