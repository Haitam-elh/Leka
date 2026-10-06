"""Knowledge quality: each thing's and area's score, and its history.

Revision ID: 9a5c3e7f1b20
Revises: 7b3d9e1f2a64
Created: 2026-10-07

LEKA-381. How far what LEKA knows can be trusted — one score per thing and
per area (a team, an application, a column, the workspace), rewritten by
each run that measures it (`quality_scores`), and a point of its history
each time it moves (`quality_history`), kept a year.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9a5c3e7f1b20"
down_revision: str | None = "7b3d9e1f2a64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPES = "scope IN ('entity', 'team', 'application', 'column', 'workspace')"
LEVELS = "level IN ('high', 'medium', 'low')"
DIMENSIONS = ("completeness", "freshness", "consistency", "confidence")


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


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def _dimensions() -> list[sa.Column[object]]:
    return [sa.Column(name, sa.Float(), nullable=True) for name in DIMENSIONS]


def _checks(table: str, *, dimensions: bool) -> list[sa.CheckConstraint]:
    checks = [
        sa.CheckConstraint(SCOPES, name=op.f(f"ck_{table}_scope")),
        sa.CheckConstraint(LEVELS, name=op.f(f"ck_{table}_level")),
        sa.CheckConstraint("score >= 0 AND score <= 1", name=op.f(f"ck_{table}_score_range")),
    ]
    if dimensions:
        checks += [
            sa.CheckConstraint(
                f"{name} IS NULL OR ({name} >= 0 AND {name} <= 1)",
                name=op.f(f"ck_{table}_{name}_range"),
            )
            for name in DIMENSIONS
        ]
    return checks


def upgrade() -> None:
    _table(
        "quality_scores",
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("subject_name", sa.String(length=500), nullable=False),
        sa.Column("subject_kind", sa.String(length=50), nullable=True),
        sa.Column("column", sa.String(length=20), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        *_dimensions(),
        _jsonb("factors", "{}"),
        _jsonb("missing", "[]"),
        _jsonb("areas", "[]"),
        sa.Column("entities", sa.Integer(), server_default="1", nullable=False),
        sa.Column("capped", sa.String(length=30), nullable=True),
        _jsonb("provenance", "{}"),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        others=(
            sa.UniqueConstraint("workspace_id", "key", name="uq_quality_scores_key"),
            *_checks("quality_scores", dimensions=True),
        ),
    )
    op.create_index(
        "ix_quality_scores_workspace_scope_score",
        "quality_scores",
        ["workspace_id", "scope", "score"],
    )
    op.create_index(
        "ix_quality_scores_workspace_subject", "quality_scores", ["workspace_id", "subject_id"]
    )

    _table(
        "quality_history",
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        *_dimensions(),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        others=tuple(_checks("quality_history", dimensions=False)),
    )
    op.create_index(
        "ix_quality_history_workspace_key_at",
        "quality_history",
        ["workspace_id", "key", "measured_at"],
    )
    op.create_index(
        "ix_quality_history_workspace_at", "quality_history", ["workspace_id", "measured_at"]
    )


def downgrade() -> None:
    op.drop_table("quality_history")
    op.drop_table("quality_scores")
