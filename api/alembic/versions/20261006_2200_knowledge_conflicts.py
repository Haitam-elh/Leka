"""Knowledge conflicts: what the sources disagree on, settled by someone.

Revision ID: 7b3d9e1f2a64
Revises: 4e9a2c7b1d58
Created: 2026-10-06

LEKA-382. What the model's sources disagree on is a conflict
(`knowledge_conflicts`): every side, who says it, how much each source is
believed, what LEKA recommends, where it stands, every decision. How much
the workspace says a source is to be believed is an authority rule
(`authority_rules`). A decision's facts are the model's validated facts
(`model_assertions`): an attribute kept — or, for a relationship a thing
has one of, the others refuted, a new kind of fact, `absence`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7b3d9e1f2a64"
down_revision: str | None = "4e9a2c7b1d58"
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


def _assertion_checks(kinds: str, said: str) -> None:
    for name in ("kind", "relationship_said"):
        op.drop_constraint(op.f(f"ck_model_assertions_{name}"), "model_assertions", type_="check")
    op.create_check_constraint(op.f("ck_model_assertions_kind"), "model_assertions", kinds)
    op.create_check_constraint(
        op.f("ck_model_assertions_relationship_said"), "model_assertions", said
    )


def upgrade() -> None:
    _assertion_checks(
        "kind IN ('attribute', 'relationship', 'absence')",
        "(kind IN ('relationship', 'absence')) = (from_entity_id IS NOT NULL "
        "AND to_entity_id IS NOT NULL AND relationship_type IS NOT NULL)",
    )

    _table(
        "knowledge_conflicts",
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("subject_name", sa.String(length=500), nullable=False),
        sa.Column("subject_kind", sa.String(length=50), nullable=True),
        sa.Column("about", sa.String(length=100), nullable=False),
        sa.Column("relationship", sa.String(length=50), nullable=True),
        _jsonb("chosen", None),
        _jsonb("sides", "[]"),
        _jsonb("recommendation", "{}"),
        sa.Column("statement", sa.Text(), nullable=False),
        _jsonb("provenance", "{}"),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        _jsonb("resolution", None),
        _jsonb("decided_values", "[]"),
        _jsonb("history", "[]"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_run_id", sa.UUID(), nullable=False),
        sa.Column("last_run_id", sa.UUID(), nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        others=(
            sa.UniqueConstraint("workspace_id", "key", name="uq_knowledge_conflicts_key"),
            sa.CheckConstraint(
                "status IN ('open', 'resolved', 'dismissed', 'gone')",
                name=op.f("ck_knowledge_conflicts_status"),
            ),
            sa.CheckConstraint(
                "kind IN ('attribute', 'relationship')", name=op.f("ck_knowledge_conflicts_kind")
            ),
        ),
    )
    for name, columns in (
        ("status", ["workspace_id", "status"]),
        ("seen", ["workspace_id", "last_seen_at"]),
        ("subject", ["workspace_id", "subject_id"]),
    ):
        op.create_index(f"ix_knowledge_conflicts_workspace_{name}", "knowledge_conflicts", columns)

    _table(
        "authority_rules",
        sa.Column("about", sa.String(length=100), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("stance", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        others=(
            sa.UniqueConstraint(
                "workspace_id", "about", "source_id", name="uq_authority_rules_about_source"
            ),
            sa.CheckConstraint(
                "stance IN ('prefer', 'avoid')", name=op.f("ck_authority_rules_stance")
            ),
            sa.ForeignKeyConstraint(
                ["source_id"],
                ["sources.id"],
                name=op.f("fk_authority_rules_source_id_sources"),
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["users.id"],
                name=op.f("fk_authority_rules_created_by_users"),
                ondelete="SET NULL",
            ),
        ),
    )


def downgrade() -> None:
    op.drop_table("authority_rules")
    op.drop_table("knowledge_conflicts")
    # A refuted relationship is a decision no older model can hold.
    op.execute("DELETE FROM model_assertions WHERE kind = 'absence'")
    _assertion_checks(
        "kind IN ('attribute', 'relationship')",
        "(kind = 'relationship') = (from_entity_id IS NOT NULL AND to_entity_id IS NOT NULL "
        "AND relationship_type IS NOT NULL)",
    )
