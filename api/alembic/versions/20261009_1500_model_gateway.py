"""Model gateway: a workspace's own language model, and every call to one.

Revision ID: 8c3f5a1d7e94
Revises: 6b1e9d4c2f73
Created: 2026-10-09

LEKA-394. A workspace's own model (`workspace_models`): its provider, its
model or Azure deployment, its address, its key encrypted (rotated with the
others, scripts/rotate_encryption_key.py), whether it is on, whether it is
the only one the workspace allows, whether it answered when last tested.
Every call to a model (`model_calls`): for what, about what, which provider,
model and version, by which route and which try, its tokens, its estimated
cost, how long — or why it failed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8c3f5a1d7e94"
down_revision: str | None = "6b1e9d4c2f73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_calls",
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("ref", sa.String(length=100), nullable=True),
        sa.Column("tier", sa.String(length=10), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=120), nullable=True),
        sa.Column("route", sa.String(length=12), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("owner", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_thinking", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=True),
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
            name=op.f("fk_model_calls_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_calls")),
    )
    op.create_index(
        "ix_model_calls_workspace_at", "model_calls", ["workspace_id", "at"], unique=False
    )
    op.create_index(
        op.f("ix_model_calls_workspace_id"), "model_calls", ["workspace_id"], unique=False
    )
    op.create_table(
        "workspace_models",
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("api_version", sa.String(length=30), nullable=True),
        sa.Column("key_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("key_hint", sa.String(length=8), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("exclusive", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=10), server_default="untested", nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_workspace_models_changed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_models_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_models")),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_models_workspace"),
    )
    op.create_index(
        op.f("ix_workspace_models_workspace_id"), "workspace_models", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_workspace_models_workspace_id"), table_name="workspace_models")
    op.drop_table("workspace_models")
    op.drop_index(op.f("ix_model_calls_workspace_id"), table_name="model_calls")
    op.drop_index("ix_model_calls_workspace_at", table_name="model_calls")
    op.drop_table("model_calls")
