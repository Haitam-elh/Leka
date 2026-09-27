"""Extracted records: what extraction made of each indexed record.

Revision ID: 9c4e2a7b1d35
Revises: 3f7a9c1d2e84
Created: 2026-09-27

LEKA-354. One new table, nothing else touched.

`extracted_records` holds one row per `source_records` row: the
ExtractedRecord as JSON, or why there is none (a failure code and a message
naming a field). `checksum` and `extractor_version` are what the record was
extracted from and by: when either changes, the record is extracted again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9c4e2a7b1d35"
down_revision: str | None = "3f7a9c1d2e84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("extracted", "failed")
FAILURES = ("unsupported", "malformed")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "extracted_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("extractor", sa.String(length=100), nullable=True),
        sa.Column("extractor_version", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failure_code", sa.String(length=20), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_extracted_records_status")),
        sa.CheckConstraint(
            "failure_code IS NULL OR " + _in("failure_code", FAILURES),
            name=op.f("ck_extracted_records_failure_code"),
        ),
        sa.CheckConstraint(
            "(status = 'extracted') = (result IS NOT NULL AND failure_code IS NULL)",
            name=op.f("ck_extracted_records_result_or_failure"),
        ),
        sa.CheckConstraint(
            "length(checksum) = 64", name=op.f("ck_extracted_records_checksum_is_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_extracted_records_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_extracted_records_workspace_source",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            ondelete="CASCADE",
            name=op.f("fk_extracted_records_source_record_id_source_records"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extracted_records")),
        sa.UniqueConstraint("source_record_id", name="uq_extracted_records_source_record"),
    )
    op.create_index(
        op.f("ix_extracted_records_workspace_id"), "extracted_records", ["workspace_id"]
    )
    op.create_index(
        "ix_extracted_records_source_status", "extracted_records", ["source_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_extracted_records_source_status", table_name="extracted_records")
    op.drop_index(op.f("ix_extracted_records_workspace_id"), table_name="extracted_records")
    op.drop_table("extracted_records")
