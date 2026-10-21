"""Which of LEKA's models answers first in a workspace (2026-10-21): chosen
by its admin among those LEKA holds a key for — Gemini, Mistral.

Revision ID: 3c7e1a9d5f24
Revises: 8b4d2f6a1c93
Created: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3c7e1a9d5f24"
down_revision: str | None = "8b4d2f6a1c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_model_defaults",
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
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
            ["changed_by"],
            ["users.id"],
            name=op.f("fk_workspace_model_defaults_changed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_model_defaults_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_model_defaults")),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_model_defaults_workspace"),
    )
    op.create_index(
        op.f("ix_workspace_model_defaults_workspace_id"),
        "workspace_model_defaults",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workspace_model_defaults_workspace_id"), table_name="workspace_model_defaults"
    )
    op.drop_table("workspace_model_defaults")
