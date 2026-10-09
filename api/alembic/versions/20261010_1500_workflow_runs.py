"""Workflow engine: every run of a workflow, its steps, what happened.

Revision ID: 7f3a8e2c5b41
Revises: 4d9c2b7e6a15
Created: 2026-10-10

LEKA-397. A run (`workflow_runs`): which workflow, which version — its steps
as they were when it was asked — asked by whom with what, for which
intention; where it stands, which step stopped it, how many times it was
retried. Its steps (`workflow_run_steps`): each one's state, attempts, what
it found, why it was skipped or failed. What happened
(`workflow_run_events`): append-only, the database refuses to change one.
The workflows themselves are capabilities: their versions are the
catalogue's (capability_registrations).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7f3a8e2c5b41"
down_revision: str | None = "4d9c2b7e6a15"
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


def _workspace(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id"],
        ["workspaces.id"],
        name=op.f(f"fk_{table}_workspace_id_workspaces"),
        ondelete="CASCADE",
    )


def _run(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "run_id"],
        ["workflow_runs.workspace_id", "workflow_runs.id"],
        name=f"fk_{table}_run",
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        _jsonb("spec", "{}"),
        sa.Column("status", sa.String(length=10), nullable=False),
        _jsonb("inputs", "{}"),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("intention_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.String(length=40), nullable=True),
        sa.Column("failed_step", sa.String(length=60), nullable=True),
        sa.Column("retries", sa.Integer(), server_default="0", nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_base(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_workflow_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_workflow_runs_requested_by_users"),
            ondelete="SET NULL",
        ),
        _workspace("workflow_runs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_runs")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_workflow_runs_workspace_id_id"),
    )
    op.create_index(
        "ix_workflow_runs_workspace_queued", "workflow_runs", ["workspace_id", "queued_at"]
    )
    op.create_index(op.f("ix_workflow_runs_workspace_id"), "workflow_runs", ["workspace_id"])

    op.create_table(
        "workflow_run_steps",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("step", sa.String(length=60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("uses", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason", sa.String(length=60), nullable=True),
        _jsonb("output", "{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_base(),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'not_reached')",
            name=op.f("ck_workflow_run_steps_status"),
        ),
        _run("workflow_run_steps"),
        _workspace("workflow_run_steps"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_run_steps")),
        sa.UniqueConstraint("run_id", "step", name="uq_workflow_run_steps_step"),
    )
    op.create_index(
        op.f("ix_workflow_run_steps_workspace_id"), "workflow_run_steps", ["workspace_id"]
    )

    op.create_table(
        "workflow_run_events",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("step", sa.String(length=60), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        _jsonb("detail", "{}"),
        *_base(),
        _run("workflow_run_events"),
        _workspace("workflow_run_events"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_run_events")),
    )
    op.create_index("ix_workflow_run_events_run", "workflow_run_events", ["run_id", "at", "seq"])
    op.create_index(
        op.f("ix_workflow_run_events_workspace_id"), "workflow_run_events", ["workspace_id"]
    )
    op.execute(
        """
        CREATE FUNCTION workflow_run_events_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'workflow_run_events is append-only: an event is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER workflow_run_events_append_only
        BEFORE UPDATE ON workflow_run_events
        FOR EACH ROW EXECUTE FUNCTION workflow_run_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER workflow_run_events_append_only ON workflow_run_events")
    op.execute("DROP FUNCTION workflow_run_events_append_only()")
    op.drop_table("workflow_run_events")
    op.drop_table("workflow_run_steps")
    op.drop_table("workflow_runs")
