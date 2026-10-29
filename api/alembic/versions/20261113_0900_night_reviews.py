"""The night review (2026-10-29): what LEKA went through overnight, and the
points it found to look at — kept, one row a review.

Revision ID: 5e8c2a7f4b19
Revises: 9b2e4d7f1a35
Created: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5e8c2a7f4b19"
down_revision: str | None = "9b2e4d7f1a35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "night_reviews",
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=10), nullable=False),
        sa.Column(
            "checked",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "points",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("asked_by", sa.UUID(), nullable=True),
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
        sa.CheckConstraint("trigger IN ('night', 'asked')", name=op.f("ck_night_reviews_trigger")),
        sa.ForeignKeyConstraint(
            ["asked_by"],
            ["users.id"],
            name=op.f("fk_night_reviews_asked_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_night_reviews_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_night_reviews")),
    )
    op.create_index(
        op.f("ix_night_reviews_workspace_id"), "night_reviews", ["workspace_id"], unique=False
    )
    op.create_index("ix_night_reviews_workspace_at", "night_reviews", ["workspace_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_night_reviews_workspace_at", table_name="night_reviews")
    op.drop_index(op.f("ix_night_reviews_workspace_id"), table_name="night_reviews")
    op.drop_table("night_reviews")
