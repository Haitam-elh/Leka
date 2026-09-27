"""Source settings: versions of a source's scope rules and mapping.

Revision ID: 5a3d8e2f9c41
Revises: 2b9f4c7e1a58
Created: 2026-09-28

LEKA-351. One new table; and `sync_runs.trigger` accepts `settings` — the
full pass a change of scope rules queues.

`source_settings` is append-only: one row per version of a source's scope
rules (include / exclude) and mapping into the company model, with who made
it. The current settings are the highest version.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5a3d8e2f9c41"
down_revision: str | None = "2b9f4c7e1a58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "scope", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "mapping", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_source_settings_version_positive")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_source_settings_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_source_settings_workspace_source",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_source_settings_created_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_settings")),
        sa.UniqueConstraint("source_id", "version", name="uq_source_settings_source_version"),
    )
    op.create_index(op.f("ix_source_settings_workspace_id"), "source_settings", ["workspace_id"])

    op.drop_constraint(op.f("ck_sync_runs_trigger"), "sync_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_runs_trigger"),
        "sync_runs",
        "trigger IN ('activation', 'schedule', 'manual', 'settings')",
    )


def downgrade() -> None:
    # A pass a settings change started was, before this revision, a manual one.
    op.execute("UPDATE sync_runs SET trigger = 'manual' WHERE trigger = 'settings'")
    op.drop_constraint(op.f("ck_sync_runs_trigger"), "sync_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_runs_trigger"),
        "sync_runs",
        "trigger IN ('activation', 'schedule', 'manual')",
    )
    op.drop_index(op.f("ix_source_settings_workspace_id"), table_name="source_settings")
    op.drop_table("source_settings")
