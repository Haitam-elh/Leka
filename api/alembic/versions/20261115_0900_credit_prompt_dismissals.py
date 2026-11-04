"""The AI capacity's prompts put aside: by whom, which threshold, which month.

Revision ID: 7c41e9a2b6d3
Revises: 3d7a1f9c5e62
Created: 2026-11-04

LEKA-527. At 90 % and 100 % of a month's AI credits, the application offers
the next plan in a banner. `credit_prompt_dismissals`: a person's « Plus
tard » or « Fermer » — for that threshold, that month and the allowance it
was seen on, once (unique): the 100 % prompt still comes after the 90 % one
is put aside, and a new month or a plan changed mid-month prompts anew.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c41e9a2b6d3"
down_revision: str | None = "3d7a1f9c5e62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credit_prompt_dismissals",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("allowance", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
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
            name=op.f("fk_credit_prompt_dismissals_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_credit_prompt_dismissals_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_prompt_dismissals")),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            "period",
            "threshold",
            "allowance",
            name="uq_credit_prompt_dismissals_once",
        ),
    )
    op.create_index(
        op.f("ix_credit_prompt_dismissals_workspace_id"),
        "credit_prompt_dismissals",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_table("credit_prompt_dismissals")
