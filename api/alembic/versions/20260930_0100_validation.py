"""Validation: what processed records are worth, before they are trusted.

Revision ID: 3e7b9d1c5a82
Revises: 9a4d2f7c1e35
Created: 2026-09-30

LEKA-358. One new table; a column on `resolved_entities`; and
`processing_runs.stage` accepts `validation`.

`validated_records`: one row per normalised record — valid, warning or
quarantined, its issues and what to do about them, its quality and what
made it (completeness, consistency, freshness, confidence), when its record
was last seen, and the processing run that validated it. Deleted with its
normalised record, and with its source.

`resolved_entities.quality`: the best quality validation gave the records
an entity is made of — none for an entity only named by others.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3e7b9d1c5a82"
down_revision: str | None = "9a4d2f7c1e35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "validated_records",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("normalised_record_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_key", sa.String(length=1000), nullable=True),
        sa.Column(
            "status",
            sa.Enum("valid", "warning", "quarantined", name="status", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "issues", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("quality", sa.Float(), nullable=False),
        sa.Column("completeness", sa.Float(), nullable=False),
        sa.Column("consistency", sa.Float(), nullable=False),
        sa.Column("freshness", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validator_version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "status IN ('valid', 'warning', 'quarantined')",
            name=op.f("ck_validated_records_status"),
        ),
        sa.CheckConstraint(
            "quality >= 0 AND quality <= 1 AND completeness >= 0 AND completeness <= 1 AND consistency >= 0 AND consistency <= 1 AND freshness >= 0 AND freshness <= 1 AND confidence >= 0 AND confidence <= 1",
            name=op.f("ck_validated_records_scores_range"),
        ),
        sa.ForeignKeyConstraint(
            ["normalised_record_id"],
            ["normalised_records.id"],
            name=op.f("fk_validated_records_normalised_record_id_normalised_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["processing_runs.id"],
            name=op.f("fk_validated_records_run_id_processing_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_validated_records_workspace_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_validated_records_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validated_records")),
        sa.UniqueConstraint("normalised_record_id", name="uq_validated_records_normalised_record"),
    )
    op.create_index(
        "ix_validated_records_source_status",
        "validated_records",
        ["source_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_validated_records_workspace_id"),
        "validated_records",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_validated_records_workspace_validated_at",
        "validated_records",
        ["workspace_id", "validated_at"],
        unique=False,
    )
    op.add_column("resolved_entities", sa.Column("quality", sa.Float(), nullable=True))

    op.drop_constraint(op.f("ck_processing_runs_stage"), "processing_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_processing_runs_stage"),
        "processing_runs",
        "stage IN ('extraction', 'parsing', 'normalisation', 'validation')",
    )


def downgrade() -> None:
    # A validation run did not exist before this revision.
    op.execute("DELETE FROM processing_runs WHERE stage = 'validation'")
    op.drop_constraint(op.f("ck_processing_runs_stage"), "processing_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_processing_runs_stage"),
        "processing_runs",
        "stage IN ('extraction', 'parsing', 'normalisation')",
    )
    op.drop_column("resolved_entities", "quality")
    op.drop_index("ix_validated_records_workspace_validated_at", table_name="validated_records")
    op.drop_index(op.f("ix_validated_records_workspace_id"), table_name="validated_records")
    op.drop_index("ix_validated_records_source_status", table_name="validated_records")
    op.drop_table("validated_records")
