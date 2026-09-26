"""Source records: what was seen of each vendor object, per source.

Revision ID: 6b1e8d4f2a73
Revises: 3f7a9c2d5e18
Created: 2026-09-27

LEKA-353, decided with Haitam on 2026-09-27. One new table, nothing else
touched.

`source_records` is the per-record index: one row per (source, kind,
external_id) with the checksum of its latest payload, when it was first
and last seen and by which run, the batch holding its latest version, and
when it was found gone. It is what deduplicates, what a full pass's sweep
marks deleted, and what the purge job reads to rewrite batches.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "6b1e8d4f2a73"
down_revision: str | None = "3f7a9c2d5e18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=500), nullable=False),
        sa.Column("container", sa.String(length=500), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload_key", sa.String(length=500), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(kind) > 0 AND length(external_id) > 0",
            name=op.f("ck_source_records_identity_not_empty"),
        ),
        sa.CheckConstraint(
            "length(checksum) = 64", name=op.f("ck_source_records_checksum_is_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_source_records_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_source_records_workspace_source",
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"],
            ["sync_runs.id"],
            ondelete="SET NULL",
            name=op.f("fk_source_records_last_seen_run_id_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_records")),
        sa.UniqueConstraint(
            "source_id", "kind", "external_id", name="uq_source_records_source_kind_external"
        ),
    )
    op.create_index(op.f("ix_source_records_workspace_id"), "source_records", ["workspace_id"])
    op.create_index(
        "ix_source_records_sweep", "source_records", ["source_id", "kind", "last_seen_run_id"]
    )
    op.create_index(
        "ix_source_records_to_purge",
        "source_records",
        ["source_id"],
        postgresql_where=sa.text("deleted_at IS NOT NULL AND payload_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_source_records_to_purge", table_name="source_records")
    op.drop_index("ix_source_records_sweep", table_name="source_records")
    op.drop_index(op.f("ix_source_records_workspace_id"), table_name="source_records")
    op.drop_table("source_records")
