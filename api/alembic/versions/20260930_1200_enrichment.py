"""Enrichment: what the resolved entities are to one another, and what follows.

Revision ID: 5c2e9f4b7a13
Revises: 3e7b9d1c5a82
Created: 2026-09-30

LEKA-359. Three new tables, made again whole at each enrichment run of a
workspace.

`enriched_relationships`: the relationships between resolved entities —
stated by a source (between keys, now between the things they are) or
inferred by an enrichment rule — each with its rule, confidence, evidence,
provenance, and whether it joins two tools' things (`cross_source`).
`entity_enrichments`: the attributes enrichment adds to an entity, never
one its sources state, each with its rule, confidence, evidence and the
keys it was made from. `enrichment_runs`: each run, the resolution run it
read, and the enrichers that failed inside it.

No foreign key to `resolved_entities`: resolution makes those again at each
of its runs, ids kept, and the last enrichment stays readable until the
next replaces it. All deleted with their workspace.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5c2e9f4b7a13"
down_revision: str | None = "3e7b9d1c5a82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "enrichment_runs",
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_run_id", sa.UUID(), nullable=True),
        sa.Column("enricher_version", sa.Integer(), nullable=False),
        sa.Column(
            "counts", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "failures", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("error", sa.String(length=200), nullable=True),
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
            "status IN ('running', 'succeeded', 'failed', 'abandoned')",
            name=op.f("ck_enrichment_runs_status"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_enrichment_runs_finished_after_started"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_enrichment_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_enrichment_runs")),
    )
    op.create_index(
        op.f("ix_enrichment_runs_workspace_id"), "enrichment_runs", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_enrichment_runs_workspace_started_at",
        "enrichment_runs",
        ["workspace_id", "started_at"],
        unique=False,
    )
    op.create_table(
        "enriched_relationships",
        sa.Column("from_entity_id", sa.UUID(), nullable=False),
        sa.Column("to_entity_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("rule", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("cross_source", sa.Boolean(), nullable=False),
        sa.Column("sources", sa.Integer(), server_default="0", nullable=False),
        sa.Column("evidence", sa.String(length=1000), nullable=False),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=False),
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
            "origin IN ('stated', 'inferred')", name=op.f("ck_enriched_relationships_origin")
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_enriched_relationships_confidence_range"),
        ),
        sa.CheckConstraint(
            "from_entity_id <> to_entity_id", name=op.f("ck_enriched_relationships_not_to_itself")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["enrichment_runs.id"],
            name=op.f("fk_enriched_relationships_run_id_enrichment_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_enriched_relationships_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_enriched_relationships")),
        sa.UniqueConstraint(
            "workspace_id",
            "from_entity_id",
            "to_entity_id",
            "type",
            name="uq_enriched_relationships_edge",
        ),
    )
    op.create_index(
        "ix_enriched_relationships_to",
        "enriched_relationships",
        ["workspace_id", "to_entity_id", "type"],
        unique=False,
    )
    op.create_index(
        "ix_enriched_relationships_workspace_confidence",
        "enriched_relationships",
        ["workspace_id", "confidence"],
        unique=False,
    )
    op.create_index(
        op.f("ix_enriched_relationships_workspace_id"),
        "enriched_relationships",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "entity_enrichments",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("attribute", sa.String(length=100), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rule", sa.String(length=100), nullable=False),
        sa.Column("evidence", sa.String(length=1000), nullable=False),
        sa.Column(
            "inputs", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=False),
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
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_entity_enrichments_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["enrichment_runs.id"],
            name=op.f("fk_entity_enrichments_run_id_enrichment_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_entity_enrichments_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_enrichments")),
        sa.UniqueConstraint(
            "workspace_id", "entity_id", "attribute", name="uq_entity_enrichments_attribute"
        ),
    )
    op.create_index(
        op.f("ix_entity_enrichments_workspace_id"),
        "entity_enrichments",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_entity_enrichments_workspace_id"), table_name="entity_enrichments")
    op.drop_table("entity_enrichments")
    op.drop_index(
        op.f("ix_enriched_relationships_workspace_id"), table_name="enriched_relationships"
    )
    op.drop_index(
        "ix_enriched_relationships_workspace_confidence", table_name="enriched_relationships"
    )
    op.drop_index("ix_enriched_relationships_to", table_name="enriched_relationships")
    op.drop_table("enriched_relationships")
    op.drop_index("ix_enrichment_runs_workspace_started_at", table_name="enrichment_runs")
    op.drop_index(op.f("ix_enrichment_runs_workspace_id"), table_name="enrichment_runs")
    op.drop_table("enrichment_runs")
