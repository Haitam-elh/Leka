"""Roles and policies: roles of the workspace's own, who holds them, its
policies, and the history of every change to them.

Revision ID: 6a1f3c8e2d57
Revises: 9e4b2d7c1a83
Created: 2026-10-13

LEKA-403. A role of the workspace's own (`workspace_roles`): a base role —
member or admin — with the permissions it adds and those it takes away;
given to a person (`role_assignments`). Its policies (`workspace_policies`):
for these actions, these roles, these resources — refuse, or allow by
exception — at a priority. Every change (`governance_events`): what, who,
when, before and after — append-only; who did it forgotten with their
account.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "6a1f3c8e2d57"
down_revision: str | None = "9e4b2d7c1a83"
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


def _user(table: str, column: str, ondelete: str = "SET NULL") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete=ondelete
    )


def _workspace(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id"],
        ["workspaces.id"],
        name=op.f(f"fk_{table}_workspace_id_workspaces"),
        ondelete="CASCADE",
    )


def _indexed(table: str) -> None:
    op.create_index(op.f(f"ix_{table}_workspace_id"), table, ["workspace_id"])


def upgrade() -> None:
    op.create_table(
        "workspace_roles",
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("base", sa.String(length=10), nullable=False),
        _jsonb("added", "[]"),
        _jsonb("removed", "[]"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        *_base(),
        sa.CheckConstraint("base IN ('member', 'admin')", name=op.f("ck_workspace_roles_base")),
        _user("workspace_roles", "created_by"),
        _workspace("workspace_roles"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_roles")),
        sa.UniqueConstraint("workspace_id", "key", name="uq_workspace_roles_key"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_workspace_roles_workspace_id_id"),
    )
    _indexed("workspace_roles")

    op.create_table(
        "role_assignments",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("assigned_by", sa.UUID(), nullable=True),
        *_base(),
        _user("role_assignments", "user_id", "CASCADE"),
        _user("role_assignments", "assigned_by"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "role_id"],
            ["workspace_roles.workspace_id", "workspace_roles.id"],
            name="fk_role_assignments_role",
            ondelete="CASCADE",
        ),
        _workspace("role_assignments"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_assignments")),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_role_assignments_user"),
    )
    _indexed("role_assignments")

    op.create_table(
        "workspace_policies",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("effect", sa.String(length=5), nullable=False),
        _jsonb("actions", "[]"),
        _jsonb("roles", "[]"),
        _jsonb("conditions", "{}"),
        sa.Column("priority", sa.Integer(), server_default="50", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        *_base(),
        sa.CheckConstraint(
            "effect IN ('deny', 'allow')", name=op.f("ck_workspace_policies_effect")
        ),
        sa.CheckConstraint(
            "priority >= 0 AND priority <= 100", name=op.f("ck_workspace_policies_priority")
        ),
        _user("workspace_policies", "created_by"),
        _workspace("workspace_policies"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_policies")),
    )
    _indexed("workspace_policies")

    op.create_table(
        "governance_events",
        sa.Column("subject_type", sa.String(length=12), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_base(),
        sa.CheckConstraint(
            "subject_type IN ('role', 'policy', 'assignment')",
            name=op.f("ck_governance_events_subject_type"),
        ),
        _user("governance_events", "by"),
        _workspace("governance_events"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_governance_events")),
    )
    op.create_index(
        "ix_governance_events_workspace_at", "governance_events", ["workspace_id", "at"]
    )
    _indexed("governance_events")
    op.execute(
        """
        CREATE FUNCTION governance_events_append_only() RETURNS trigger AS $$
        BEGIN
            IF NEW."by" IS NULL AND to_jsonb(NEW) - 'by' = to_jsonb(OLD) - 'by' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'governance_events is append-only: a change is never rewritten'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER governance_events_append_only
        BEFORE UPDATE ON governance_events
        FOR EACH ROW EXECUTE FUNCTION governance_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER governance_events_append_only ON governance_events")
    op.execute("DROP FUNCTION governance_events_append_only()")
    op.drop_table("governance_events")
    op.drop_table("workspace_policies")
    op.drop_table("role_assignments")
    op.drop_table("workspace_roles")
