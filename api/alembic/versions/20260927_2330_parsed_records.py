"""Parsed records: what parsing read in each extraction.

Revision ID: 4d8b1f6e3a92
Revises: 9c4e2a7b1d35
Created: 2026-09-27

LEKA-355. One new table, nothing else touched.

`parsed_records` holds one row per `extracted_records` row that was
extracted: the ParsedRecord as JSON (facts, structure, quality), or why
there is none. `checksum`, `extractor_version` and `parser_version` are what
it was parsed from and by: when one changes, it is parsed again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4d8b1f6e3a92"
down_revision: str | None = "9c4e2a7b1d35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "parsed_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extracted_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("extractor_version", sa.Integer(), nullable=True),
        sa.Column("parser_version", sa.Integer(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failure_code", sa.String(length=20), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('parsed', 'failed')", name=op.f("ck_parsed_records_status")),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code = 'malformed'",
            name=op.f("ck_parsed_records_failure_code"),
        ),
        sa.CheckConstraint(
            "(status = 'parsed') = (result IS NOT NULL AND failure_code IS NULL)",
            name=op.f("ck_parsed_records_result_or_failure"),
        ),
        sa.CheckConstraint(
            "length(checksum) = 64", name=op.f("ck_parsed_records_checksum_is_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_parsed_records_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_parsed_records_workspace_source",
        ),
        sa.ForeignKeyConstraint(
            ["extracted_record_id"],
            ["extracted_records.id"],
            ondelete="CASCADE",
            name=op.f("fk_parsed_records_extracted_record_id_extracted_records"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parsed_records")),
        sa.UniqueConstraint("extracted_record_id", name="uq_parsed_records_extracted_record"),
    )
    op.create_index(op.f("ix_parsed_records_workspace_id"), "parsed_records", ["workspace_id"])
    op.create_index("ix_parsed_records_source_status", "parsed_records", ["source_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_parsed_records_source_status", table_name="parsed_records")
    op.drop_index(op.f("ix_parsed_records_workspace_id"), table_name="parsed_records")
    op.drop_table("parsed_records")
