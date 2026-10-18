"""The channels connected by a webhook (LEKA-496): Slack, Microsoft Teams,
Discord — one each a workspace, its URL encrypted.

Revision ID: d1dd03b07ab2
Revises: 7a2c9e4b1d36
Created: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1dd03b07ab2"
down_revision: str | None = "7a2c9e4b1d36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitoring_channel_endpoints",
        sa.Column("channel", sa.String(length=10), nullable=False),
        sa.Column("webhook_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("hint", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="untested", nullable=False),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
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
            "channel IN ('slack', 'teams', 'discord')",
            name=op.f("ck_monitoring_channel_endpoints_channel"),
        ),
        sa.CheckConstraint(
            "status IN ('untested', 'operational', 'failing')",
            name=op.f("ck_monitoring_channel_endpoints_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_monitoring_channel_endpoints_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_monitoring_channel_endpoints_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monitoring_channel_endpoints")),
        sa.UniqueConstraint(
            "workspace_id", "channel", name="uq_monitoring_channel_endpoints_channel"
        ),
    )
    op.create_index(
        op.f("ix_monitoring_channel_endpoints_workspace_id"),
        "monitoring_channel_endpoints",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_monitoring_channel_endpoints_workspace_id"),
        table_name="monitoring_channel_endpoints",
    )
    op.drop_table("monitoring_channel_endpoints")
