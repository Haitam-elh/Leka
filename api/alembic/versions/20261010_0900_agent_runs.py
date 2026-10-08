"""Agent runtime: every run of an agent, and its steps.

Revision ID: 2e7b4c9a1f58
Revises: 8c3f5a1d7e94
Created: 2026-10-10

LEKA-395. A run (`agent_runs`): which agent, which version, asked by whom
with what, for which intention, on which context — where it stands (queued,
running, succeeded, failed, cancelled), what it delivered, which model
answered, how many tools it called, or why it failed. Its steps
(`agent_run_events`): queued, started, its context, a tool withheld or
called and what came of it, the model's answer, how it ended — append-only,
the database refuses to change one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2e7b4c9a1f58"
down_revision: str | None = "8c3f5a1d7e94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column[object]]:
    return [
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
    ]


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        _jsonb("inputs", "{}"),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("intention_id", sa.UUID(), nullable=True),
        sa.Column("context_id", sa.UUID(), nullable=True),
        sa.Column("context_version", sa.Integer(), nullable=True),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error", sa.String(length=40), nullable=True),
        _jsonb("detail", "{}"),
        sa.Column("provider", sa.String(length=20), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_base(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_agent_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_agent_runs_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_agent_runs_workspace_id_id"),
    )
    op.create_index(
        "ix_agent_runs_workspace_queued", "agent_runs", ["workspace_id", "queued_at"], unique=False
    )
    op.create_index(op.f("ix_agent_runs_workspace_id"), "agent_runs", ["workspace_id"])

    op.create_table(
        "agent_run_events",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        _jsonb("detail", "{}"),
        *_base(),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_agent_run_events_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_run_events_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_run_events")),
    )
    op.create_index("ix_agent_run_events_run", "agent_run_events", ["run_id", "at", "seq"])
    op.create_index(op.f("ix_agent_run_events_workspace_id"), "agent_run_events", ["workspace_id"])

    # A step is never changed; the run it belongs to may be erased with its
    # workspace, and its steps with it.
    op.execute(
        """
        CREATE FUNCTION agent_run_events_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'agent_run_events is append-only: a step is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_run_events_append_only
        BEFORE UPDATE ON agent_run_events
        FOR EACH ROW EXECUTE FUNCTION agent_run_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER agent_run_events_append_only ON agent_run_events")
    op.execute("DROP FUNCTION agent_run_events_append_only()")
    op.drop_table("agent_run_events")
    op.drop_table("agent_runs")
