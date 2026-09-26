"""Source syncs: how far each capability of each source has been read.

Revision ID: 8d2e4f6a1b90
Revises: 5c0f1a7e2b34
Created: 2026-09-26

LEKA-352. One new table, nothing else touched.

`source_syncs` holds one row per (source, capability): the cursor the next
incremental pass starts from (`since`, when the last successful pass
started), when the last pass started, succeeded, and read everything, how
many records it read, how many passes in a row failed, and the last
diagnostic. Deleted with its source, like everything that references one.

`capability` is not checked by the database, like `sources.kind` since
LEKA-344: adding a capability to a connector must not be a migration.
`status` is, as every closed set is (ADR 006).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8d2e4f6a1b90"
down_revision: str | None = "5c0f1a7e2b34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("idle", "running", "failed")


def upgrade() -> None:
    op.create_table(
        "source_syncs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="idle", nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_full_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_last_run", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_total", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(repr(s) for s in STATUSES) + ")",
            name=op.f("ck_source_syncs_status"),
        ),
        sa.CheckConstraint(
            "length(capability) > 0", name=op.f("ck_source_syncs_capability_not_empty")
        ),
        sa.CheckConstraint(
            "records_last_run >= 0", name=op.f("ck_source_syncs_records_last_run_not_negative")
        ),
        sa.CheckConstraint(
            "records_total >= 0", name=op.f("ck_source_syncs_records_total_not_negative")
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name=op.f("ck_source_syncs_consecutive_failures_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_source_syncs_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_source_syncs_workspace_source",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_syncs")),
        sa.UniqueConstraint("source_id", "capability", name="uq_source_syncs_source_capability"),
    )
    op.create_index(op.f("ix_source_syncs_workspace_id"), "source_syncs", ["workspace_id"])
    op.create_index("ix_source_syncs_last_succeeded_at", "source_syncs", ["last_succeeded_at"])


def downgrade() -> None:
    op.drop_index("ix_source_syncs_last_succeeded_at", table_name="source_syncs")
    op.drop_index(op.f("ix_source_syncs_workspace_id"), table_name="source_syncs")
    op.drop_table("source_syncs")
