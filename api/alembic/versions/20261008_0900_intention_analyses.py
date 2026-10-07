"""Intention analyses: what answered an intention, run on its context.

Revision ID: 5e7b2c9d4a61
Revises: 8b4f1d6a2c97
Created: 2026-10-08

LEKA-388. Each analysis of an intention is kept (`intention_analyses`): the
capabilities chosen and why, what each did, and the result — findings,
probable causes, impact, what is uncertain or missing, how sure — every
piece of evidence with where it came from.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5e7b2c9d4a61"
down_revision: str | None = "8b4f1d6a2c97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "status IN ('running', 'complete', 'partial', 'inconclusive', 'failed', 'blocked')"
TRIGGERS = "trigger IN ('created', 'asked_again', 'requested', 'sweep')"


def _jsonb(name: str, default: str | None) -> sa.Column[object]:
    if default is None:
        return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "intention_analyses",
        sa.Column("intention_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("context_id", sa.UUID(), nullable=True),
        sa.Column("context_version", sa.Integer(), nullable=True),
        sa.Column("readiness", sa.String(length=10), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _jsonb("selection", "[]"),
        _jsonb("steps", "[]"),
        _jsonb("result", None),
        sa.Column("error", sa.String(length=200), nullable=True),
        _jsonb("detail", "{}"),
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
        sa.CheckConstraint(STATUSES, name=op.f("ck_intention_analyses_status")),
        sa.CheckConstraint(TRIGGERS, name=op.f("ck_intention_analyses_trigger")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            name="fk_intention_analyses_intention",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_intention_analyses_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_intention_analyses_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intention_analyses")),
        sa.UniqueConstraint("intention_id", "number", name="uq_intention_analyses_number"),
    )
    op.create_index(
        op.f("ix_intention_analyses_workspace_id"), "intention_analyses", ["workspace_id"]
    )
    op.create_index(
        "ix_intention_analyses_intention", "intention_analyses", ["intention_id", "number"]
    )


def downgrade() -> None:
    op.drop_table("intention_analyses")
