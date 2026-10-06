"""Knowledge enrichment: the candidates LEKA proposes, the facts validated.

Revision ID: 4e9a2c7b1d58
Revises: 2b8d4f6a1c93
Created: 2026-10-06

LEKA-380. An enrichment an analysis proposes is a candidate
(`enrichment_candidates`): what it proposes — a relationship, an attribute
— how sure, what shows it, where it stands, every decision taken on it.
Once validated, it is a fact of the company model (`model_assertions`,
under the candidate's id), which every build applies; withdrawn, it is
deleted, and the next build undoes it. A build records the fingerprint of
the facts it applied (`model_runs.assertions`): a fact validated since is
something new to build. A relationship such a fact makes has the origin
`accepted`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4e9a2c7b1d58"
down_revision: str | None = "2b8d4f6a1c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table(name: str, *columns: sa.Column[object], others: Sequence[object] = ()) -> None:
    """A workspace's table, as leka.db's mixin makes them."""
    op.create_table(
        name,
        *columns,
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
        *others,
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{name}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    op.create_index(op.f(f"ix_{name}_workspace_id"), name, ["workspace_id"])


def _jsonb(name: str, default: str | None) -> sa.Column[object]:
    if default is None:
        return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def upgrade() -> None:
    op.drop_constraint(op.f("ck_relationships_origin"), "relationships", type_="check")
    op.create_check_constraint(
        op.f("ck_relationships_origin"),
        "relationships",
        "origin IN ('stated', 'inferred', 'accepted')",
    )
    op.add_column("model_runs", sa.Column("assertions", sa.String(length=64), nullable=True))

    _table(
        "model_assertions",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("attribute", sa.String(length=100), nullable=True),
        _jsonb("value", None),
        sa.Column("overrides", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("from_entity_id", sa.UUID(), nullable=True),
        sa.Column("to_entity_id", sa.UUID(), nullable=True),
        sa.Column("relationship_type", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rule", sa.String(length=100), nullable=False),
        sa.Column("evidence", sa.Text(), server_default="", nullable=False),
        _jsonb("provenance", "{}"),
        others=(
            sa.CheckConstraint(
                "kind IN ('attribute', 'relationship')", name=op.f("ck_model_assertions_kind")
            ),
            sa.CheckConstraint(
                "confidence >= 0 AND confidence <= 1",
                name=op.f("ck_model_assertions_confidence_range"),
            ),
            sa.CheckConstraint(
                "(kind = 'attribute') = (entity_id IS NOT NULL AND attribute IS NOT NULL)",
                name=op.f("ck_model_assertions_attribute_said"),
            ),
            sa.CheckConstraint(
                "(kind = 'relationship') = (from_entity_id IS NOT NULL AND to_entity_id IS NOT "
                "NULL AND relationship_type IS NOT NULL)",
                name=op.f("ck_model_assertions_relationship_said"),
            ),
        ),
    )

    _table(
        "enrichment_candidates",
        sa.Column("analyzer", sa.String(length=60), nullable=False),
        sa.Column("analyzer_version", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("family", sa.String(length=30), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("subject_name", sa.String(length=500), nullable=False),
        sa.Column("subject_kind", sa.String(length=50), nullable=True),
        sa.Column("relationship", sa.String(length=50), nullable=True),
        sa.Column("start_id", sa.UUID(), nullable=True),
        sa.Column("start_name", sa.String(length=500), nullable=True),
        sa.Column("start_kind", sa.String(length=50), nullable=True),
        sa.Column("end_id", sa.UUID(), nullable=True),
        sa.Column("end_name", sa.String(length=500), nullable=True),
        sa.Column("end_kind", sa.String(length=50), nullable=True),
        sa.Column("attribute", sa.String(length=100), nullable=True),
        _jsonb("value", None),
        _jsonb("current", None),
        sa.Column("overrides", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        _jsonb("params", "{}"),
        sa.Column("confidence", sa.Float(), nullable=False),
        _jsonb("evidence", "[]"),
        _jsonb("provenance", "{}"),
        sa.Column("status", sa.String(length=20), server_default="proposed", nullable=False),
        sa.Column("decided_via", sa.String(length=10), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        _jsonb("history", "[]"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_run_id", sa.UUID(), nullable=False),
        sa.Column("last_run_id", sa.UUID(), nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        others=(
            sa.UniqueConstraint("workspace_id", "key", name="uq_enrichment_candidates_key"),
            sa.CheckConstraint(
                "status IN ('proposed', 'accepted', 'rejected', 'withdrawn')",
                name=op.f("ck_enrichment_candidates_status"),
            ),
            sa.CheckConstraint(
                "kind IN ('relationship', 'attribute')",
                name=op.f("ck_enrichment_candidates_kind"),
            ),
            sa.CheckConstraint(
                "decided_via IS NULL OR decided_via IN ('person', 'policy')",
                name=op.f("ck_enrichment_candidates_decided_via"),
            ),
            sa.CheckConstraint(
                "confidence >= 0 AND confidence <= 1",
                name=op.f("ck_enrichment_candidates_confidence_range"),
            ),
            sa.CheckConstraint(
                "(status IN ('accepted', 'rejected')) = (decided_at IS NOT NULL)",
                name=op.f("ck_enrichment_candidates_decided_when"),
            ),
            sa.ForeignKeyConstraint(
                ["decided_by"],
                ["users.id"],
                name=op.f("fk_enrichment_candidates_decided_by_users"),
                ondelete="SET NULL",
            ),
        ),
    )
    op.create_index(
        "ix_enrichment_candidates_workspace_status",
        "enrichment_candidates",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_enrichment_candidates_workspace_seen",
        "enrichment_candidates",
        ["workspace_id", "last_seen_at"],
    )
    op.create_index(
        "ix_enrichment_candidates_workspace_subject",
        "enrichment_candidates",
        ["workspace_id", "subject_id"],
    )


def downgrade() -> None:
    op.drop_table("enrichment_candidates")
    op.drop_table("model_assertions")
    op.drop_column("model_runs", "assertions")
    # Relationships validated go with the facts that made them.
    op.execute("DELETE FROM relationships WHERE origin = 'accepted'")
    op.drop_constraint(op.f("ck_relationships_origin"), "relationships", type_="check")
    op.create_check_constraint(
        op.f("ck_relationships_origin"), "relationships", "origin IN ('stated', 'inferred')"
    )
