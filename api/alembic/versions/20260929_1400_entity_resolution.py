"""Entity resolution: what the workspace's candidates are, as real things.

Revision ID: 9a4d2f7c1e35
Revises: 6c3e8a1f2d94
Created: 2026-09-29

LEKA-357. Four new tables, and an index on `normalised_records`.

`resolved_entities`: one row per real thing the workspace's sources show —
its type, the key that says it best, its name and every other, what its
sources say it is, and where they disagree (`conflicts`, every value kept).
`resolved_keys`: every key it goes by, per source that gave it — the
provenance, and the lookup from a key. `resolution_decisions`: each merge,
link and ambiguity, with its rule, confidence and evidence.
`resolution_runs`: each run over a workspace. All made again at each run,
the ids kept; deleted with their workspace, the keys and decisions with
their entity.

`ix_normalised_records_workspace_normalised_at` answers the question a
resolution run is queued on: has anything been normalised since?
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9a4d2f7c1e35"
down_revision: str | None = "6c3e8a1f2d94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resolution_runs",
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fingerprint", sa.String(length=100), nullable=True),
        sa.Column("resolver_version", sa.Integer(), nullable=False),
        sa.Column(
            "counts", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
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
            name=op.f("ck_resolution_runs_status"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_resolution_runs_finished_after_started"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_resolution_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resolution_runs")),
    )
    op.create_index(
        op.f("ix_resolution_runs_workspace_id"), "resolution_runs", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_resolution_runs_workspace_started_at",
        "resolution_runs",
        ["workspace_id", "started_at"],
        unique=False,
    )
    op.create_table(
        "resolved_entities",
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=1000), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column(
            "names", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "conflicts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sources", sa.Integer(), nullable=False),
        sa.Column("resolver_version", sa.Integer(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
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
            name=op.f("ck_resolved_entities_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_resolved_entities_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resolved_entities")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_resolved_entities_workspace_id_id"),
    )
    op.create_index(
        op.f("ix_resolved_entities_workspace_id"),
        "resolved_entities",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_resolved_entities_workspace_type_name",
        "resolved_entities",
        ["workspace_id", "type", "name"],
        unique=False,
    )
    op.create_table(
        "resolution_decisions",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("other_entity_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("rule", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "keys", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("evidence", sa.String(length=1000), nullable=False),
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
            "(kind = 'link') = (other_entity_id IS NOT NULL)",
            name=op.f("ck_resolution_decisions_link_has_other"),
        ),
        sa.CheckConstraint(
            "kind IN ('merge', 'link', 'ambiguous')", name=op.f("ck_resolution_decisions_kind")
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_resolution_decisions_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["resolved_entities.workspace_id", "resolved_entities.id"],
            name="fk_resolution_decisions_workspace_entity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "other_entity_id"],
            ["resolved_entities.workspace_id", "resolved_entities.id"],
            name="fk_resolution_decisions_workspace_other",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_resolution_decisions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resolution_decisions")),
    )
    op.create_index(
        "ix_resolution_decisions_entity", "resolution_decisions", ["entity_id"], unique=False
    )
    op.create_index(
        "ix_resolution_decisions_other", "resolution_decisions", ["other_entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_resolution_decisions_workspace_id"),
        "resolution_decisions",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "resolved_keys",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=1000), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=True),
        sa.Column("records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("named", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("example_record_id", sa.UUID(), nullable=True),
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
            "kind IN ('key', 'alias', 'derived')", name=op.f("ck_resolved_keys_kind")
        ),
        sa.CheckConstraint(
            "records >= 0 AND named >= 0", name=op.f("ck_resolved_keys_counts_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["resolved_entities.workspace_id", "resolved_entities.id"],
            name="fk_resolved_keys_workspace_entity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_resolved_keys_workspace_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_resolved_keys_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resolved_keys")),
        sa.UniqueConstraint(
            "entity_id", "key", "source_id", name="uq_resolved_keys_entity_key_source"
        ),
    )
    op.create_index("ix_resolved_keys_entity", "resolved_keys", ["entity_id"], unique=False)
    op.create_index(
        op.f("ix_resolved_keys_workspace_id"), "resolved_keys", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_resolved_keys_workspace_key", "resolved_keys", ["workspace_id", "key"], unique=False
    )
    op.create_index(
        "ix_normalised_records_workspace_normalised_at",
        "normalised_records",
        ["workspace_id", "normalised_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_normalised_records_workspace_normalised_at", table_name="normalised_records")
    op.drop_index("ix_resolved_keys_workspace_key", table_name="resolved_keys")
    op.drop_index(op.f("ix_resolved_keys_workspace_id"), table_name="resolved_keys")
    op.drop_index("ix_resolved_keys_entity", table_name="resolved_keys")
    op.drop_table("resolved_keys")
    op.drop_index(op.f("ix_resolution_decisions_workspace_id"), table_name="resolution_decisions")
    op.drop_index("ix_resolution_decisions_other", table_name="resolution_decisions")
    op.drop_index("ix_resolution_decisions_entity", table_name="resolution_decisions")
    op.drop_table("resolution_decisions")
    op.drop_index("ix_resolved_entities_workspace_type_name", table_name="resolved_entities")
    op.drop_index(op.f("ix_resolved_entities_workspace_id"), table_name="resolved_entities")
    op.drop_table("resolved_entities")
    op.drop_index("ix_resolution_runs_workspace_started_at", table_name="resolution_runs")
    op.drop_index(op.f("ix_resolution_runs_workspace_id"), table_name="resolution_runs")
    op.drop_table("resolution_runs")
