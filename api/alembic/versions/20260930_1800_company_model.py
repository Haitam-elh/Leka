"""The company model: canonical entities, versioned, with their provenance.

Revision ID: 8b3f6d2a9e41
Revises: 5c2e9f4b7a13
Created: 2026-09-30

LEKA-361. `entities` and `relationships` existed since the first schema, one
row per (source, external id), and nothing wrote them. They become the
company model: one row per real thing, whose id is the resolved entity's
(LEKA-357), built from resolution and enrichment (LEKA-359).

`entities` loses `source_id` and `external_id` — a thing is seen by several
sources, which `provenance` now lists with every key it goes by — and gains
its key, a lifecycle (active, dormant, archived, removed), a version and the
hash of what it says, its schema's version, the quality of its records,
where each attribute came from, and its dates. `relationships` loses
`source_id` too and gains whether a source stated it or a rule inferred it,
the rule, whether it joins two tools' things, and what it was made from.
Both type CHECK constraints take the new kinds (docs/adr/006-enum-storage.md).

`entity_versions`: what an entity said at each of its versions, and what
changed. `model_runs`: each build, the enrichment run it read, the model's
version, its counts or its error.

The rows of both tables are removed first: nothing wrote them — the seed
script aside — and the model is made again from resolution by the next
build, which the hourly sweep queues. The downgrade removes them too: the
old columns cannot be filled from the new.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8b3f6d2a9e41"
down_revision: str | None = "5c2e9f4b7a13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ENTITY_TYPES = (
    "service",
    "repository",
    "incident",
    "deployment",
    "person",
    "document",
    "infra_resource",
    "database",
)
ENTITY_TYPES = (
    *OLD_ENTITY_TYPES,
    "team",
    "project",
    "issue",
    "pull_request",
    "commit",
    "release",
)
OLD_RELATIONSHIP_TYPES = (
    "depends_on",
    "owns",
    "deployed_to",
    "mentions",
    "caused_by",
    "member_of",
)
RELATIONSHIP_TYPES = (
    *OLD_RELATIONSHIP_TYPES,
    "part_of",
    "owned_by",
    "maintained_by",
    "authored_by",
    "assigned_to",
    "reviewed_by",
    "reported_by",
    "led_by",
    "affects",
    "resolves",
    "implements",
    "merges",
    "child_of",
    "in_network",
)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _retype(table: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(f"ck_{table}_type"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_type"), table, _one_of("type", values))


def upgrade() -> None:
    op.execute("DELETE FROM relationships")
    op.execute("DELETE FROM entities")

    op.create_table(
        "model_runs",
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrichment_run_id", sa.UUID(), nullable=True),
        sa.Column("model_version", sa.Integer(), nullable=False),
        sa.Column(
            "counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
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
            name=op.f("ck_model_runs_status"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_model_runs_finished_after_started"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_model_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_runs")),
    )
    op.create_index(op.f("ix_model_runs_workspace_id"), "model_runs", ["workspace_id"])
    op.create_index(
        "ix_model_runs_workspace_started_at", "model_runs", ["workspace_id", "started_at"]
    )

    op.drop_constraint(op.f("uq_entities_workspace_source_external"), "entities", type_="unique")
    op.drop_constraint(op.f("fk_entities_workspace_source"), "entities", type_="foreignkey")
    op.drop_column("entities", "external_id")
    op.drop_column("entities", "source_id")
    op.add_column("entities", sa.Column("key", sa.String(length=1000), nullable=False))
    op.add_column(
        "entities",
        sa.Column("lifecycle", sa.String(length=20), server_default="active", nullable=False),
    )
    op.add_column(
        "entities", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column(
        "entities", sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column(
        "entities",
        sa.Column("content_hash", sa.String(length=64), server_default="", nullable=False),
    )
    op.add_column("entities", sa.Column("quality", sa.Float(), nullable=True))
    op.add_column(
        "entities",
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column("entities", sa.Column("first_seen_at", sa.DateTime(timezone=True)))
    op.add_column("entities", sa.Column("removed_at", sa.DateTime(timezone=True)))
    op.add_column("entities", sa.Column("lifecycle_changed_at", sa.DateTime(timezone=True)))
    _retype("entities", ENTITY_TYPES)
    op.create_check_constraint(
        op.f("ck_entities_lifecycle"),
        "entities",
        _one_of("lifecycle", ("active", "dormant", "archived", "removed")),
    )
    op.create_check_constraint(op.f("ck_entities_version_positive"), "entities", "version >= 1")
    op.create_check_constraint(
        op.f("ck_entities_removed_when"),
        "entities",
        "(lifecycle = 'removed') = (removed_at IS NOT NULL)",
    )
    op.create_index("ix_entities_workspace_key", "entities", ["workspace_id", "key"])
    op.create_index("ix_entities_workspace_type_name", "entities", ["workspace_id", "type", "name"])

    op.drop_constraint(
        op.f("fk_relationships_workspace_source"), "relationships", type_="foreignkey"
    )
    op.drop_column("relationships", "source_id")
    op.add_column(
        "relationships",
        sa.Column("origin", sa.String(length=10), server_default="stated", nullable=False),
    )
    op.add_column(
        "relationships",
        sa.Column("rule", sa.String(length=100), server_default="stated", nullable=False),
    )
    op.add_column(
        "relationships",
        sa.Column("cross_source", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "relationships",
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    _retype("relationships", RELATIONSHIP_TYPES)
    op.create_check_constraint(
        op.f("ck_relationships_origin"), "relationships", "origin IN ('stated', 'inferred')"
    )

    op.create_table(
        "entity_versions",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "changed",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["model_runs.id"],
            name=op.f("fk_entity_versions_run_id_model_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["entities.workspace_id", "entities.id"],
            name="fk_entity_versions_workspace_entity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_entity_versions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_versions")),
        sa.UniqueConstraint("entity_id", "version", name="uq_entity_versions_entity_version"),
    )
    op.create_index(op.f("ix_entity_versions_workspace_id"), "entity_versions", ["workspace_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_entity_versions_workspace_id"), table_name="entity_versions")
    op.drop_table("entity_versions")

    op.execute("DELETE FROM relationships")
    op.execute("DELETE FROM entities")

    op.drop_constraint(op.f("ck_relationships_origin"), "relationships", type_="check")
    _retype("relationships", OLD_RELATIONSHIP_TYPES)
    for column in ("provenance", "cross_source", "rule", "origin"):
        op.drop_column("relationships", column)
    op.add_column("relationships", sa.Column("source_id", sa.UUID(), nullable=False))
    op.create_foreign_key(
        op.f("fk_relationships_workspace_source"),
        "relationships",
        "sources",
        ["workspace_id", "source_id"],
        ["workspace_id", "id"],
        ondelete="CASCADE",
    )

    op.drop_index("ix_entities_workspace_type_name", table_name="entities")
    op.drop_index("ix_entities_workspace_key", table_name="entities")
    for constraint in ("removed_when", "version_positive", "lifecycle"):
        op.drop_constraint(op.f(f"ck_entities_{constraint}"), "entities", type_="check")
    _retype("entities", OLD_ENTITY_TYPES)
    for column in (
        "lifecycle_changed_at",
        "removed_at",
        "first_seen_at",
        "provenance",
        "quality",
        "content_hash",
        "schema_version",
        "version",
        "lifecycle",
        "key",
    ):
        op.drop_column("entities", column)
    op.add_column("entities", sa.Column("source_id", sa.UUID(), nullable=False))
    op.add_column("entities", sa.Column("external_id", sa.String(length=500), nullable=False))
    op.create_foreign_key(
        op.f("fk_entities_workspace_source"),
        "entities",
        "sources",
        ["workspace_id", "source_id"],
        ["workspace_id", "id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        op.f("uq_entities_workspace_source_external"),
        "entities",
        ["workspace_id", "source_id", "external_id"],
    )

    op.drop_index("ix_model_runs_workspace_started_at", table_name="model_runs")
    op.drop_index(op.f("ix_model_runs_workspace_id"), table_name="model_runs")
    op.drop_table("model_runs")
