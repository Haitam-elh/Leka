"""Intention plans: what approved decisions became, and how they ran.

Revision ID: 4c8e2b7f9d13
Revises: 7a3d9e1c5b42
Created: 2026-10-08

LEKA-391. The systems a workspace authorized LEKA to act through
(`action_endpoints`, their signing secret encrypted); the plan of an
approved decision (`intention_plans`), its steps with the evidence of each
(`intention_plan_steps`), and everything that happened to it
(`intention_plan_events`) — append-only, the database refusing to change
an event.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4c8e2b7f9d13"
down_revision: str | None = "7a3d9e1c5b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_endpoints",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column(
            "actions", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "environments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "targets", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("last_called_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_action_endpoints_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_action_endpoints_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_endpoints")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_action_endpoints_workspace_id_id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_action_endpoints_name"),
    )
    op.create_index(
        op.f("ix_action_endpoints_workspace_id"), "action_endpoints", ["workspace_id"], unique=False
    )
    op.create_table(
        "intention_plans",
        sa.Column("intention_id", sa.UUID(), nullable=False),
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("started_by", sa.UUID(), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "checks", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
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
            "status IN ('planned', 'scheduled', 'running', 'succeeded', 'failed', 'cancelled', 'blocked')",
            name=op.f("ck_intention_plans_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_intention_plans_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["started_by"],
            ["users.id"],
            name=op.f("fk_intention_plans_started_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "decision_id"],
            ["intention_decisions.workspace_id", "intention_decisions.id"],
            name="fk_intention_plans_decision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            name="fk_intention_plans_intention",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_intention_plans_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intention_plans")),
        sa.UniqueConstraint("intention_id", "number", name="uq_intention_plans_number"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_intention_plans_workspace_id_id"),
    )
    op.create_index(
        "ix_intention_plans_due", "intention_plans", ["status", "scheduled_for"], unique=False
    )
    op.create_index(
        "ix_intention_plans_intention", "intention_plans", ["intention_id", "number"], unique=False
    )
    op.create_index(
        op.f("ix_intention_plans_workspace_id"), "intention_plans", ["workspace_id"], unique=False
    )
    op.create_table(
        "intention_plan_events",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=10), nullable=False),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
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
        sa.ForeignKeyConstraint(
            ["by"],
            ["users.id"],
            name=op.f("fk_intention_plan_events_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "plan_id"],
            ["intention_plans.workspace_id", "intention_plans.id"],
            name="fk_intention_plan_events_plan",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_intention_plan_events_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intention_plan_events")),
    )
    op.create_index(
        "ix_intention_plan_events_plan", "intention_plan_events", ["plan_id", "at"], unique=False
    )
    op.create_index(
        op.f("ix_intention_plan_events_workspace_id"),
        "intention_plan_events",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "intention_plan_steps",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.String(length=60), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column(
            "targets", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("environment", sa.String(length=60), nullable=True),
        sa.Column(
            "constraints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("executor", sa.String(length=20), nullable=False),
        sa.Column("endpoint_id", sa.UUID(), nullable=True),
        sa.Column("endpoint_name", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column(
            "evidence", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
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
            "executor IN ('webhook', 'manual')", name=op.f("ck_intention_plan_steps_executor")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'awaiting', 'succeeded', 'failed', 'cancelled', 'skipped')",
            name=op.f("ck_intention_plan_steps_status"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "plan_id"],
            ["intention_plans.workspace_id", "intention_plans.id"],
            name="fk_intention_plan_steps_plan",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_intention_plan_steps_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intention_plan_steps")),
        sa.UniqueConstraint("plan_id", "position", name="uq_intention_plan_steps_position"),
    )
    op.create_index(
        op.f("ix_intention_plan_steps_workspace_id"),
        "intention_plan_steps",
        ["workspace_id"],
        unique=False,
    )

    # An execution's history is append-only, as an intention's is (LEKA-384):
    # the one change allowed is who did it forgotten, with the user.
    op.execute(
        """
        CREATE FUNCTION intention_plan_events_append_only() RETURNS trigger AS $$
        BEGIN
            IF NEW."by" IS NULL AND to_jsonb(NEW) - 'by' = to_jsonb(OLD) - 'by' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'intention_plan_events is append-only: an event is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER intention_plan_events_append_only
        BEFORE UPDATE ON intention_plan_events
        FOR EACH ROW EXECUTE FUNCTION intention_plan_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER intention_plan_events_append_only ON intention_plan_events")
    op.execute("DROP FUNCTION intention_plan_events_append_only()")
    op.drop_index(op.f("ix_intention_plan_steps_workspace_id"), table_name="intention_plan_steps")
    op.drop_table("intention_plan_steps")
    op.drop_index(op.f("ix_intention_plan_events_workspace_id"), table_name="intention_plan_events")
    op.drop_index("ix_intention_plan_events_plan", table_name="intention_plan_events")
    op.drop_table("intention_plan_events")
    op.drop_index(op.f("ix_intention_plans_workspace_id"), table_name="intention_plans")
    op.drop_index("ix_intention_plans_intention", table_name="intention_plans")
    op.drop_index("ix_intention_plans_due", table_name="intention_plans")
    op.drop_table("intention_plans")
    op.drop_index(op.f("ix_action_endpoints_workspace_id"), table_name="action_endpoints")
    op.drop_table("action_endpoints")
