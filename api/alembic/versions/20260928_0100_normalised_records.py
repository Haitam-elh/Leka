"""Normalised records: the candidates normalisation made of each parse.

Revision ID: 7e2c5a9d4b16
Revises: 4d8b1f6e3a92
Created: 2026-09-28

LEKA-356. One new table, nothing else touched.

`normalised_records` holds one row per `parsed_records` row that was parsed:
the NormalisedRecord as JSON (the record's entity under its canonical key,
the people, services and teams it names, relationships between keys), or
why there is none. `entity_key` is indexed per workspace for entity
resolution (LEKA-357) to find every record naming one key.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7e2c5a9d4b16"
down_revision: str | None = "4d8b1f6e3a92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "normalised_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parsed_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("extractor_version", sa.Integer(), nullable=True),
        sa.Column("parser_version", sa.Integer(), nullable=False),
        sa.Column("normaliser_version", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_key", sa.String(length=1000), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failure_code", sa.String(length=20), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("normalised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('normalised', 'failed')", name=op.f("ck_normalised_records_status")
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ('unsupported', 'invalid', 'malformed')",
            name=op.f("ck_normalised_records_failure_code"),
        ),
        sa.CheckConstraint(
            "(status = 'normalised') = "
            "(result IS NOT NULL AND entity_key IS NOT NULL AND failure_code IS NULL)",
            name=op.f("ck_normalised_records_result_or_failure"),
        ),
        sa.CheckConstraint(
            "length(checksum) = 64", name=op.f("ck_normalised_records_checksum_is_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_normalised_records_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_normalised_records_workspace_source",
        ),
        sa.ForeignKeyConstraint(
            ["parsed_record_id"],
            ["parsed_records.id"],
            ondelete="CASCADE",
            name=op.f("fk_normalised_records_parsed_record_id_parsed_records"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_normalised_records")),
        sa.UniqueConstraint("parsed_record_id", name="uq_normalised_records_parsed_record"),
    )
    op.create_index(
        op.f("ix_normalised_records_workspace_id"), "normalised_records", ["workspace_id"]
    )
    op.create_index(
        "ix_normalised_records_source_status", "normalised_records", ["source_id", "status"]
    )
    op.create_index(
        "ix_normalised_records_entity_key", "normalised_records", ["workspace_id", "entity_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_normalised_records_entity_key", table_name="normalised_records")
    op.drop_index("ix_normalised_records_source_status", table_name="normalised_records")
    op.drop_index(op.f("ix_normalised_records_workspace_id"), table_name="normalised_records")
    op.drop_table("normalised_records")
