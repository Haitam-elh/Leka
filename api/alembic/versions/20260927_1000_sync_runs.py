"""Sync runs: what each pass over a source did.

Revision ID: 3f7a9c2d5e18
Revises: 8d2e4f6a1b90
Created: 2026-09-27

LEKA-353. One new table, nothing else touched.

`sync_runs` holds one row per pass: what started it (activation, schedule,
manual), whether it read everything, when it started and ended, its
progress as each batch is committed (the capability it is on, records,
payloads, bytes), and how it ended — succeeded, failed, or abandoned when
the next pass found it still running. Deleted with its source.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3f7a9c2d5e18"
down_revision: str | None = "8d2e4f6a1b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGERS = ("activation", "schedule", "manual")
STATUSES = ("running", "succeeded", "failed", "abandoned")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=50), nullable=False),
        sa.Column("full_read", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capability", sa.String(length=50), nullable=True),
        sa.Column("records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payloads", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(_in("trigger", TRIGGERS), name=op.f("ck_sync_runs_trigger")),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_sync_runs_status")),
        sa.CheckConstraint(
            "records >= 0 AND payloads >= 0 AND bytes >= 0",
            name=op.f("ck_sync_runs_counts_not_negative"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_sync_runs_finished_after_started"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_sync_runs_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_sync_runs_workspace_source",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
    )
    op.create_index(op.f("ix_sync_runs_workspace_id"), "sync_runs", ["workspace_id"])
    op.create_index("ix_sync_runs_source_started_at", "sync_runs", ["source_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_sync_runs_source_started_at", table_name="sync_runs")
    op.drop_index(op.f("ix_sync_runs_workspace_id"), table_name="sync_runs")
    op.drop_table("sync_runs")
