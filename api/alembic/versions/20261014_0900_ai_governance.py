"""AI governance: the workspace's AI controls, what each did, whom a model
call was for, agent runs held for approval.

Revision ID: 2c7e5a9f4b16
Revises: 6a1f3c8e2d57
Created: 2026-10-14

LEKA-406. A control (`ai_controls`): model access, usage limit, output
check or approval — over which work, which roles, with its kind's settings.
What one did (`ai_control_events`): which, to what work, for whom, on which
model, what it found — append-only; the person forgotten with their
account. A model call says whom it was asked for (`model_calls.user_id`).
An agent run may wait for approval (`agent_runs.status`, widened to 20,
'awaiting_approval'). A change to a control is in the governance history
(`governance_events.subject_type` 'ai_control').
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2c7e5a9f4b16"
down_revision: str | None = "6a1f3c8e2d57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_STATUSES = "'queued', 'running', 'succeeded', 'failed', 'cancelled'"
SUBJECTS = "'role', 'policy', 'assignment'"
OUTCOMES = "'refused', 'limited', 'redacted', 'blocked', 'flagged', 'held', 'approved', 'rejected'"


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


def _user(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
    )


def _workspace(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id"],
        ["workspaces.id"],
        name=op.f(f"fk_{table}_workspace_id_workspaces"),
        ondelete="CASCADE",
    )


def _check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    op.create_table(
        "ai_controls",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        _jsonb("purposes", "[]"),
        _jsonb("roles", "[]"),
        _jsonb("config", "{}"),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        *_base(),
        sa.CheckConstraint(
            "kind IN ('model_access', 'usage_limit', 'output_check', 'approval')",
            name=op.f("ck_ai_controls_kind"),
        ),
        _user("ai_controls", "created_by"),
        _workspace("ai_controls"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_controls")),
    )
    op.create_index(op.f("ix_ai_controls_workspace_id"), "ai_controls", ["workspace_id"])

    op.create_table(
        "ai_control_events",
        sa.Column("control_id", sa.UUID(), nullable=True),
        sa.Column("control_name", sa.String(length=120), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=True),
        sa.Column("ref", sa.String(length=100), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        _jsonb("detail", "{}"),
        *_base(),
        sa.CheckConstraint(f"outcome IN ({OUTCOMES})", name=op.f("ck_ai_control_events_outcome")),
        _user("ai_control_events", "user_id"),
        _workspace("ai_control_events"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_control_events")),
    )
    op.create_index(
        "ix_ai_control_events_workspace_at", "ai_control_events", ["workspace_id", "at"]
    )
    op.create_index(
        op.f("ix_ai_control_events_workspace_id"), "ai_control_events", ["workspace_id"]
    )
    op.execute(
        """
        CREATE FUNCTION ai_control_events_append_only() RETURNS trigger AS $$
        BEGIN
            IF NEW.user_id IS NULL AND to_jsonb(NEW) - 'user_id' = to_jsonb(OLD) - 'user_id' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'ai_control_events is append-only: what a control did is never rewritten'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER ai_control_events_append_only
        BEFORE UPDATE ON ai_control_events
        FOR EACH ROW EXECUTE FUNCTION ai_control_events_append_only()
        """
    )

    op.add_column("model_calls", sa.Column("user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_model_calls_user_id_users"),
        "model_calls",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column(
        "agent_runs",
        "status",
        type_=sa.String(length=20),
        existing_type=sa.String(length=10),
        existing_nullable=False,
    )
    _check("agent_runs", "status", f"status IN ('awaiting_approval', {RUN_STATUSES})")
    _check("governance_events", "subject_type", f"subject_type IN ({SUBJECTS}, 'ai_control')")


def downgrade() -> None:
    op.execute("DELETE FROM governance_events WHERE subject_type = 'ai_control'")
    _check("governance_events", "subject_type", f"subject_type IN ({SUBJECTS})")
    op.execute(
        "UPDATE agent_runs SET status = 'cancelled', finished_at = now()"
        " WHERE status = 'awaiting_approval'"
    )
    _check("agent_runs", "status", f"status IN ({RUN_STATUSES})")
    op.alter_column(
        "agent_runs",
        "status",
        type_=sa.String(length=10),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.drop_constraint(op.f("fk_model_calls_user_id_users"), "model_calls", type_="foreignkey")
    op.drop_column("model_calls", "user_id")
    op.execute("DROP TRIGGER ai_control_events_append_only ON ai_control_events")
    op.execute("DROP FUNCTION ai_control_events_append_only()")
    op.drop_table("ai_control_events")
    op.drop_table("ai_controls")
