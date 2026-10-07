"""Knowledge evolution: the model's snapshots, and the operations on its course.

Revision ID: 9c4e2a7d5b13
Revises: 9a5c3e7f1b20
Created: 2026-10-07

LEKA-383. What the company model held at a moment — how many of each kind,
in each lifecycle, how many relationships of each kind, how well each kind
is known — is a snapshot (`model_snapshots`), written by a build, or rebuilt
from the history the model keeps. A controlled change to its course — an
entity's attributes restored as a version said them, the model rebuilt —
is an operation (`model_operations`): who asked, when, why, what came of it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9c4e2a7d5b13"
down_revision: str | None = "9a5c3e7f1b20"
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


def _jsonb(name: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
    )


def _user(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
    )


def upgrade() -> None:
    # What changed over time, workspace-wide: the evolution feed's order.
    op.create_index(
        "ix_entity_versions_workspace_recorded", "entity_versions", ["workspace_id", "recorded_at"]
    )
    _table(
        "model_snapshots",
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconstructed", sa.Boolean(), server_default="false", nullable=False),
        _jsonb("counts"),
        _jsonb("measures"),
        others=(
            sa.ForeignKeyConstraint(
                ["run_id"],
                ["model_runs.id"],
                name=op.f("fk_model_snapshots_run_id_model_runs"),
                ondelete="SET NULL",
            ),
        ),
    )
    op.create_index(
        "ix_model_snapshots_workspace_built", "model_snapshots", ["workspace_id", "built_at"]
    )

    _table(
        "model_operations",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("entity_name", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        _jsonb("detail"),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_by", sa.UUID(), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        others=(
            sa.CheckConstraint(
                "kind IN ('restore', 'rebuild')", name=op.f("ck_model_operations_kind")
            ),
            sa.CheckConstraint(
                "status IN ('queued', 'applied', 'done', 'failed', 'undone')",
                name=op.f("ck_model_operations_status"),
            ),
            _user("model_operations", "requested_by"),
            _user("model_operations", "undone_by"),
        ),
    )
    op.create_index(
        "ix_model_operations_workspace_created", "model_operations", ["workspace_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("model_operations")
    op.drop_table("model_snapshots")
    op.drop_index("ix_entity_versions_workspace_recorded", table_name="entity_versions")
    # A restore's facts are decisions no older model can explain.
    op.execute("DELETE FROM model_assertions WHERE provenance ->> 'operation_id' IS NOT NULL")
