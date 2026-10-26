"""Dedicated agents (2026-10-25): an agent made for one organisation, seen and
run only by the organisations it is assigned to.

Revision ID: 4f7a2c9d1b63
Revises: 9d3c1b7e5a42
Created: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4f7a2c9d1b63"
down_revision: str | None = "9d3c1b7e5a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dedicated_agents",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("assigned_by", sa.String(length=100), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
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
            name=op.f("fk_dedicated_agents_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dedicated_agents")),
        sa.UniqueConstraint("workspace_id", "key", name="uq_dedicated_agents_key"),
    )
    op.create_index(
        op.f("ix_dedicated_agents_workspace_id"), "dedicated_agents", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dedicated_agents_workspace_id"), table_name="dedicated_agents")
    op.drop_table("dedicated_agents")
