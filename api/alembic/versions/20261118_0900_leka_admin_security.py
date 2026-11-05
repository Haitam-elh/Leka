"""LEKA ADMIN's sessions renewed, its trail closed to deletion.

Revision ID: 7c3e9a1b5d24
Revises: 4d8f2a6c9e13
Created: 2026-11-05

LEKA-546.
- `admin_sessions`: `family_id` (a device's sessions, from sign-in to their
  end, across renewals), `signed_in_at`, and `ended_reason`. The sessions
  open today are each the first of their family.
- `admin_audit_events`: `session_id`, the session an action was done in.
- The trail refused a changed row but let a row be deleted. Now it refuses
  both, and refuses to be emptied: a row is deleted only by the nightly
  sweep (`leka.admin_audit_sweep`), once it is older than six months.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c3e9a1b5d24"
down_revision: str | None = "4d8f2a6c9e13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS = (
    "signed_out",
    "renewed",
    "ended_by_self",
    "ended_by_admin",
    "password",
    "disabled",
    "reused",
)

UPDATE_ONLY = """
    CREATE OR REPLACE FUNCTION admin_audit_events_append_only() RETURNS trigger AS $$
    BEGIN
        IF to_jsonb(NEW) - 'admin_id' - 'for_workspace_id'
            = to_jsonb(OLD) - 'admin_id' - 'for_workspace_id'
           AND (NEW.admin_id IS NULL OR NEW.admin_id = OLD.admin_id)
           AND (NEW.for_workspace_id IS NULL OR NEW.for_workspace_id = OLD.for_workspace_id)
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'admin_audit_events is append-only: a row is never rewritten'
            USING ERRCODE = 'restrict_violation';
    END;
    $$ LANGUAGE plpgsql
"""

UPDATE_AND_DELETE = """
    CREATE OR REPLACE FUNCTION admin_audit_events_append_only() RETURNS trigger AS $$
    BEGIN
        IF TG_OP = 'UPDATE' THEN
            -- An admin or an organisation deleted: who it was about, forgotten.
            IF to_jsonb(NEW) - 'admin_id' - 'for_workspace_id'
                = to_jsonb(OLD) - 'admin_id' - 'for_workspace_id'
               AND (NEW.admin_id IS NULL OR NEW.admin_id = OLD.admin_id)
               AND (NEW.for_workspace_id IS NULL OR NEW.for_workspace_id = OLD.for_workspace_id)
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'admin_audit_events is append-only: a row is never rewritten'
                USING ERRCODE = 'restrict_violation';
        END IF;
        -- DELETE: the nightly sweep's, and never a row under six months old.
        IF current_setting('leka.admin_audit_sweep', true) = 'on'
           AND OLD.at < now() - interval '180 days' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'admin_audit_events is append-only: a row is deleted only when it expires'
            USING ERRCODE = 'restrict_violation';
    END;
    $$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.add_column("admin_sessions", sa.Column("family_id", sa.UUID(), nullable=True))
    op.add_column(
        "admin_sessions", sa.Column("signed_in_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("admin_sessions", sa.Column("ended_reason", sa.String(length=20), nullable=True))
    op.execute("UPDATE admin_sessions SET family_id = id, signed_in_at = created_at")
    op.execute("UPDATE admin_sessions SET ended_reason = 'signed_out' WHERE revoked_at IS NOT NULL")
    op.alter_column("admin_sessions", "family_id", nullable=False)
    op.alter_column("admin_sessions", "signed_in_at", nullable=False)
    op.create_check_constraint(
        op.f("ck_admin_sessions_ended_reason"),
        "admin_sessions",
        f"ended_reason IN ({', '.join(repr(reason) for reason in REASONS)})",
    )
    op.create_index("ix_admin_sessions_family_id", "admin_sessions", ["family_id"], unique=False)

    op.add_column("admin_audit_events", sa.Column("session_id", sa.UUID(), nullable=True))

    op.execute(UPDATE_AND_DELETE)
    op.execute("DROP TRIGGER admin_audit_events_append_only ON admin_audit_events")
    op.execute(
        """
        CREATE TRIGGER admin_audit_events_append_only
        BEFORE UPDATE OR DELETE ON admin_audit_events
        FOR EACH ROW EXECUTE FUNCTION admin_audit_events_append_only()
        """
    )
    op.execute(
        """
        CREATE FUNCTION admin_audit_events_never_emptied() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'admin_audit_events is append-only: it is never emptied'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_events_never_emptied
        BEFORE TRUNCATE ON admin_audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION admin_audit_events_never_emptied()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER admin_audit_events_never_emptied ON admin_audit_events")
    op.execute("DROP FUNCTION admin_audit_events_never_emptied()")
    op.execute("DROP TRIGGER admin_audit_events_append_only ON admin_audit_events")
    op.execute(UPDATE_ONLY)
    op.execute(
        """
        CREATE TRIGGER admin_audit_events_append_only
        BEFORE UPDATE ON admin_audit_events
        FOR EACH ROW EXECUTE FUNCTION admin_audit_events_append_only()
        """
    )
    op.drop_column("admin_audit_events", "session_id")
    op.drop_index("ix_admin_sessions_family_id", table_name="admin_sessions")
    op.drop_constraint(op.f("ck_admin_sessions_ended_reason"), "admin_sessions", type_="check")
    op.drop_column("admin_sessions", "ended_reason")
    op.drop_column("admin_sessions", "signed_in_at")
    op.drop_column("admin_sessions", "family_id")
