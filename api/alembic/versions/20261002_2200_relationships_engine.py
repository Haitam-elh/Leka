"""Relationships: their life, their history, and what is wrong with them.

Revision ID: 3c7e9b1d5f24
Revises: 8d3f6a2c9e41
Created: 2026-10-02

LEKA-368. A relationship says when it first appeared and last changed
(`first_seen_at`, `changed_at` — the existing ones, from when they were
made). `relationship_changes` keeps each one that appeared, changed or
went, at each build: their history. `relationship_issues` holds what the
last build found wrong — an end its kind's contract does not take, a loop
where none may be, two of what a thing has one of.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3c7e9b1d5f24"
down_revision: str | None = "8d3f6a2c9e41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table(name: str, *columns: sa.Column[object], checks: sa.CheckConstraint) -> None:
    """A workspace's table, as leka.db's mixin makes them."""
    op.create_table(
        name,
        *columns,
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
        checks,
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["model_runs.id"],
            name=op.f(f"fk_{name}_run_id_model_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{name}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    op.create_index(op.f(f"ix_{name}_workspace_id"), name, ["workspace_id"])


def upgrade() -> None:
    op.add_column(
        "relationships", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "relationships", sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE relationships SET first_seen_at = created_at, changed_at = created_at")

    _table(
        "relationship_changes",
        sa.Column("from_entity_id", sa.UUID(), nullable=False),
        sa.Column("to_entity_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("change", sa.String(length=10), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        checks=sa.CheckConstraint(
            "change IN ('added', 'changed', 'removed')",
            name=op.f("ck_relationship_changes_change"),
        ),
    )
    for index, columns in (
        ("ix_relationship_changes_workspace_recorded", ["workspace_id", "recorded_at"]),
        ("ix_relationship_changes_from", ["workspace_id", "from_entity_id"]),
        ("ix_relationship_changes_to", ["workspace_id", "to_entity_id"]),
    ):
        op.create_index(index, "relationship_changes", columns)

    _table(
        "relationship_issues",
        sa.Column("from_entity_id", sa.UUID(), nullable=False),
        sa.Column("to_entity_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("issue", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("rule", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        checks=sa.CheckConstraint(
            "severity IN ('error', 'warning')", name=op.f("ck_relationship_issues_severity")
        ),
    )
    op.create_index(
        "ix_relationship_issues_workspace_type", "relationship_issues", ["workspace_id", "type"]
    )


def downgrade() -> None:
    op.drop_table("relationship_issues")
    op.drop_table("relationship_changes")
    op.drop_column("relationships", "changed_at")
    op.drop_column("relationships", "first_seen_at")
