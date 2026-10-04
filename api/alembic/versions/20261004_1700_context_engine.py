"""The context engine: contexts, their versions, what each holds.

Revision ID: 40c229408919
Revises: 6f1a8c3d2b57
Created: 2026-10-04

LEKA-370. A context (`contexts`) is what LEKA assembled to understand one
request in its company context: its purpose, its subject, what it asks the
company model for, where it stands. Each assembly is a version
(`context_versions`) — made once, never changed: when, from which build of
the model, by which strategy, what it holds, or why it failed. Each version
holds its elements (`context_elements`): the entities and relationships it
was made of, as the model said them then, each with its provenance and why
it is there. All of it goes with the workspace.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "40c229408919"
down_revision: str | None = "6f1a8c3d2b57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table(name: str, *columns: sa.Column[object], others: Sequence[object] = ()) -> None:
    """A workspace's table, as leka.db's mixin makes them."""
    op.create_table(
        name,
        *columns,
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
        *others,
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{name}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    op.create_index(op.f(f"ix_{name}_workspace_id"), name, ["workspace_id"])


def _user(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
    )


def upgrade() -> None:
    _table(
        "contexts",
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("purpose", sa.String(length=2000), server_default="", nullable=False),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=True),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="assembling", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        others=(
            sa.CheckConstraint(
                "status IN ('assembling', 'assembled', 'failed', 'archived')",
                name=op.f("ck_contexts_status"),
            ),
            sa.CheckConstraint(
                "subject_type IN ('entity', 'intention', 'request')",
                name=op.f("ck_contexts_subject_type"),
            ),
            sa.CheckConstraint("current_version >= 0", name=op.f("ck_contexts_current_version")),
            _user("contexts", "created_by"),
            sa.UniqueConstraint("workspace_id", "id", name="uq_contexts_workspace_id_id"),
        ),
    )
    op.create_index(
        "ix_contexts_workspace_subject", "contexts", ["workspace_id", "subject_type", "subject_id"]
    )
    op.create_index("ix_contexts_workspace_updated_at", "contexts", ["workspace_id", "updated_at"])

    _table(
        "context_versions",
        sa.Column("context_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_version", sa.Integer(), nullable=False),
        sa.Column("element_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("dropped", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "summary", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("fingerprint", sa.String(length=64), server_default="", nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("assembled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assembled_by", sa.UUID(), nullable=True),
        others=(
            sa.CheckConstraint(
                "status IN ('assembled', 'failed')", name=op.f("ck_context_versions_status")
            ),
            sa.CheckConstraint(
                "trigger IN ('created', 'refreshed')", name=op.f("ck_context_versions_trigger")
            ),
            sa.CheckConstraint("version >= 1", name=op.f("ck_context_versions_version")),
            _user("context_versions", "assembled_by"),
            # Pinned to its context's workspace.
            sa.ForeignKeyConstraint(
                ["workspace_id", "context_id"],
                ["contexts.workspace_id", "contexts.id"],
                name="fk_context_versions_workspace_context",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("workspace_id", "id", name="uq_context_versions_workspace_id_id"),
            sa.UniqueConstraint(
                "context_id", "version", name="uq_context_versions_context_version"
            ),
        ),
    )
    op.create_index(
        "ix_context_versions_workspace_context", "context_versions", ["workspace_id", "context_id"]
    )

    _table(
        "context_elements",
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ref_id", sa.UUID(), nullable=False),
        sa.Column("ref_type", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=True),
        others=(
            sa.CheckConstraint(
                "kind IN ('entity', 'relationship')", name=op.f("ck_context_elements_kind")
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id", "version_id"],
                ["context_versions.workspace_id", "context_versions.id"],
                name="fk_context_elements_workspace_version",
                ondelete="CASCADE",
            ),
        ),
    )
    op.create_index(
        "ix_context_elements_version_position", "context_elements", ["version_id", "position"]
    )
    op.create_index(
        "ix_context_elements_workspace_ref", "context_elements", ["workspace_id", "ref_id"]
    )


def downgrade() -> None:
    op.drop_table("context_elements")
    op.drop_table("context_versions")
    op.drop_table("contexts")
