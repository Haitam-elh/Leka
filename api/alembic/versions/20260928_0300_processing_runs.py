"""Processing runs: each run of a processing stage over a source.

Revision ID: 2b9f4c7e1a58
Revises: 7e2c5a9d4b16
Created: 2026-09-28

LEKA-360. One new table, nothing else touched.

`processing_runs` holds one row per run of extraction, parsing or
normalisation over one source: status (running, succeeded, failed,
abandoned), start and end, what it did, the versions it ran with, and the
type of the error it stopped on. The history of a source's processing, and
what its processed rows are traced to.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2b9f4c7e1a58"
down_revision: str | None = "7e2c5a9d4b16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "stage IN ('extraction', 'parsing', 'normalisation')",
            name=op.f("ck_processing_runs_stage"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'abandoned')",
            name=op.f("ck_processing_runs_status"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_processing_runs_finished_after_started"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_processing_runs_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_processing_runs_workspace_source",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_runs")),
    )
    op.create_index(op.f("ix_processing_runs_workspace_id"), "processing_runs", ["workspace_id"])
    op.create_index(
        "ix_processing_runs_source_stage_started",
        "processing_runs",
        ["source_id", "stage", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_processing_runs_source_stage_started", table_name="processing_runs")
    op.drop_index(op.f("ix_processing_runs_workspace_id"), table_name="processing_runs")
    op.drop_table("processing_runs")
