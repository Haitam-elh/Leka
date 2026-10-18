"""An agent or a skill someone wishes LEKA had (LEKA-501): sent to LEKA's
team from « Demander une compétence », where it stands.

Revision ID: bb4d53f55a47
Revises: adee2d9b1cf5
Created: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bb4d53f55a47"
down_revision: str | None = "adee2d9b1cf5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capability_suggestions",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("use_case", sa.Text(), nullable=False),
        sa.Column("systems", sa.String(length=300), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="received", nullable=False),
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
            "status IN ('received', 'reviewing', 'planned', 'declined', 'done')",
            name=op.f("ck_capability_suggestions_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_capability_suggestions_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_capability_suggestions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_suggestions")),
    )
    op.create_index(
        "ix_capability_suggestions_user_created",
        "capability_suggestions",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_capability_suggestions_workspace_id"),
        "capability_suggestions",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_capability_suggestions_workspace_id"), table_name="capability_suggestions"
    )
    op.drop_index("ix_capability_suggestions_user_created", table_name="capability_suggestions")
    op.drop_table("capability_suggestions")
