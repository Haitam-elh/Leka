"""The audit trail: one record per event that matters, and how long a
workspace keeps it.

Revision ID: 8d3f6b2a9c51
Revises: 2c7e5a9f4b16
Created: 2026-10-15

LEKA-407. `audit_events`: who — a person, as which role, or LEKA itself —
did what, to what, with what outcome, from where (a network prefix, the
request); never the data it touched. Append-only, and more: the database
refuses an UPDATE (but for forgetting a person with their account) and a
DELETE (but for the retention sweep, which says so in its transaction, and
the workspace's own deletion). `audit_settings`: how many days the
workspace keeps it — 90 to 2555; none, 365.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8d3f6b2a9c51"
down_revision: str | None = "2c7e5a9f4b16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIES = (
    "'user', 'team', 'workspace', 'data', 'access', 'governance', 'decision', 'action',"
    " 'ai', 'audit'"
)


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


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=12), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("actor_type", sa.String(length=10), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_role", sa.String(length=60), nullable=True),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("target_label", sa.String(length=200), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("ip", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        *_base(),
        sa.CheckConstraint(f"category IN ({CATEGORIES})", name=op.f("ck_audit_events_category")),
        sa.CheckConstraint(
            "outcome IN ('success', 'failure', 'denied')", name=op.f("ck_audit_events_outcome")
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system')", name=op.f("ck_audit_events_actor_type")
        ),
        _user("audit_events", "actor_id"),
        _workspace("audit_events"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_workspace_id"), "audit_events", ["workspace_id"])
    op.create_index("ix_audit_events_workspace_at", "audit_events", ["workspace_id", "at"])
    op.create_index(
        "ix_audit_events_workspace_actor", "audit_events", ["workspace_id", "actor_id", "at"]
    )
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index(
        "ix_audit_events_workspace_target",
        "audit_events",
        ["workspace_id", "target_type", "target_id"],
    )
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                -- A person forgotten with their account: the one change.
                IF NEW.actor_id IS NULL
                   AND to_jsonb(NEW) - 'actor_id' = to_jsonb(OLD) - 'actor_id' THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'audit_events is append-only: an event is never rewritten'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            -- DELETE: the retention sweep, which says so; or the workspace gone.
            IF current_setting('leka.audit_sweep', true) = 'on'
               OR NOT EXISTS (SELECT 1 FROM workspaces WHERE id = OLD.workspace_id) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit_events is append-only: an event is deleted only when it expires'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
        """
    )

    op.create_table(
        "audit_settings",
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        *_base(),
        sa.CheckConstraint(
            "retention_days BETWEEN 90 AND 2555", name=op.f("ck_audit_settings_retention_days")
        ),
        _user("audit_settings", "updated_by"),
        _workspace("audit_settings"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_settings")),
        sa.UniqueConstraint("workspace_id", name="uq_audit_settings_workspace_id"),
    )
    op.create_index(op.f("ix_audit_settings_workspace_id"), "audit_settings", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("audit_settings")
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
    op.drop_table("audit_events")
