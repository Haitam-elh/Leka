"""Skill runs: every run of a skill, whatever came of it.

Revision ID: 3c6d9e1f4a72
Revises: 7f3a8e2c5b41
Created: 2026-10-12

A skill (LEKA-396) is one operation LEKA's capabilities are made of — a
read of the company model, a lookup — with its contract: what it takes,
what it gives. Each run is kept (`skill_runs`): which skill, which version
and contract (its fingerprint), called by what (LEKA's analyst, the API, an
agent) about what (`intention:<id>`…), for whom, given what — what it gave
or why not (refused, failed, timed out), and how long it took.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3c6d9e1f4a72"
down_revision: str | None = "7f3a8e2c5b41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb(name: str, *, default: str | None) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=default,
        nullable=default is None,
    )


def upgrade() -> None:
    op.create_table(
        "skill_runs",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("caller", sa.String(length=100), nullable=False),
        sa.Column("ref", sa.String(length=100), nullable=True),
        sa.Column("run_by", sa.UUID(), nullable=True),
        _jsonb("inputs", default="{}"),
        _jsonb("output", default=None),
        _jsonb("detail", default="{}"),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
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
            "status IN ('succeeded', 'refused', 'failed', 'timed_out')",
            name=op.f("ck_skill_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["run_by"],
            ["users.id"],
            name=op.f("fk_skill_runs_run_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_skill_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_runs")),
    )
    op.create_index(
        op.f("ix_skill_runs_workspace_id"), "skill_runs", ["workspace_id"], unique=False
    )
    op.create_index("ix_skill_runs_workspace_at", "skill_runs", ["workspace_id", "at"])
    op.create_index("ix_skill_runs_workspace_ref", "skill_runs", ["workspace_id", "ref", "at"])


def downgrade() -> None:
    op.drop_index("ix_skill_runs_workspace_ref", table_name="skill_runs")
    op.drop_index("ix_skill_runs_workspace_at", table_name="skill_runs")
    op.drop_index(op.f("ix_skill_runs_workspace_id"), table_name="skill_runs")
    op.drop_table("skill_runs")
