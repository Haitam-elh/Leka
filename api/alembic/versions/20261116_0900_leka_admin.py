"""LEKA ADMIN: LEKA's team, its trail, its idempotency keys, the activity journal.

Revision ID: 9b2e4c7a1f08
Revises: 7c41e9a2b6d3
Created: 2026-11-05

LEKA-544. Tables of LEKA's own, none workspace-scoped (which organisation a
row is about is `for_workspace_id`):

`admin_accounts`, `admin_sessions`: LEKA's team, apart from the customers'
users, and their signed-in devices (bearer tokens, hashed).

`admin_audit_events`: everything done and every sensitive read through LEKA
ADMIN. Append-only: the trigger below refuses an update, except the one a
foreign key makes when the admin or the organisation it is about is deleted
(it forgets who, and keeps what).

`admin_idempotency_keys`: a sensitive operation's answer, under its key.

`activity_events`, `activity_watermarks`: the activity journal, derived from
the tables that already say what happened, each fact once by its
`dedupe_key`, and how far each source has been read.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9b2e4c7a1f08"
down_revision: str | None = "7c41e9a2b6d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_watermarks",
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("read_to", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_watermarks")),
        sa.UniqueConstraint("source", name="uq_activity_watermarks_source"),
    )
    op.create_table(
        "admin_accounts",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("failed_sign_ins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sign_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
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
            "role IN ('super_admin', 'operations', 'support', 'finance')",
            name=op.f("ck_admin_accounts_role"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')", name=op.f("ck_admin_accounts_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_accounts")),
        sa.UniqueConstraint("email", name="uq_admin_accounts_email"),
    )
    op.create_table(
        "activity_events",
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("for_workspace_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("ref", sa.String(length=100), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
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
            ["for_workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_activity_events_for_workspace_id_workspaces"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_activity_events_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_events")),
        sa.UniqueConstraint("dedupe_key", name="uq_activity_events_dedupe"),
    )
    op.create_index("ix_activity_events_kind_at", "activity_events", ["kind", "at"], unique=False)
    op.create_index(
        "ix_activity_events_user_at", "activity_events", ["user_id", "at"], unique=False
    )
    op.create_index(
        "ix_activity_events_workspace_at",
        "activity_events",
        ["for_workspace_id", "at"],
        unique=False,
    )
    op.create_table(
        "admin_audit_events",
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admin_id", sa.UUID(), nullable=True),
        sa.Column("admin_email", sa.String(length=320), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("for_workspace_id", sa.UUID(), nullable=True),
        sa.Column("route", sa.String(length=200), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip_prefix", sa.String(length=64), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
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
            "outcome IN ('succeeded', 'refused', 'failed')",
            name=op.f("ck_admin_audit_events_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_accounts.id"],
            name=op.f("fk_admin_audit_events_admin_id_admin_accounts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["for_workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_admin_audit_events_for_workspace_id_workspaces"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_audit_events")),
    )
    op.create_index(
        "ix_admin_audit_events_admin_at", "admin_audit_events", ["admin_id", "at"], unique=False
    )
    op.create_index("ix_admin_audit_events_at", "admin_audit_events", ["at"], unique=False)
    op.create_index(
        "ix_admin_audit_events_workspace_at",
        "admin_audit_events",
        ["for_workspace_id", "at"],
        unique=False,
    )
    op.create_table(
        "admin_idempotency_keys",
        sa.Column("admin_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("route", sa.String(length=200), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            ["admin_id"],
            ["admin_accounts.id"],
            name=op.f("fk_admin_idempotency_keys_admin_id_admin_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_idempotency_keys")),
        sa.UniqueConstraint("admin_id", "key", name="uq_admin_idempotency_keys_key"),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("admin_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("ip_prefix", sa.String(length=64), nullable=True),
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
            ["admin_id"],
            ["admin_accounts.id"],
            name=op.f("fk_admin_sessions_admin_id_admin_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_sessions")),
        sa.UniqueConstraint("token_hash", name="uq_admin_sessions_token"),
    )
    op.create_index(
        op.f("ix_admin_sessions_admin_id"), "admin_sessions", ["admin_id"], unique=False
    )

    op.execute(
        """
        CREATE FUNCTION admin_audit_events_append_only() RETURNS trigger AS $$
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
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_events_append_only
        BEFORE UPDATE ON admin_audit_events
        FOR EACH ROW EXECUTE FUNCTION admin_audit_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER admin_audit_events_append_only ON admin_audit_events")
    op.execute("DROP FUNCTION admin_audit_events_append_only()")
    op.drop_index(op.f("ix_admin_sessions_admin_id"), table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_table("admin_idempotency_keys")
    op.drop_index("ix_admin_audit_events_workspace_at", table_name="admin_audit_events")
    op.drop_index("ix_admin_audit_events_at", table_name="admin_audit_events")
    op.drop_index("ix_admin_audit_events_admin_at", table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
    op.drop_index("ix_activity_events_workspace_at", table_name="activity_events")
    op.drop_index("ix_activity_events_user_at", table_name="activity_events")
    op.drop_index("ix_activity_events_kind_at", table_name="activity_events")
    op.drop_table("activity_events")
    op.drop_table("admin_accounts")
    op.drop_table("activity_watermarks")
