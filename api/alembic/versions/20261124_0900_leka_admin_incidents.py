"""Incidents and the admins' notifications.

Revision ID: b1323b797096
Revises: 658e6460a4b5
Created: 2026-11-07

LEKA-556. Opened by the incident watch (leka/admin/incidents.py) from what
LEKA CORE already records; LEKA's team's alone.
- `admin_incidents`: a problem, its organisation (none: the platform), its
  category, severity, status, assignee; `fingerprint` unique among the open
  ones, so a same problem adds an occurrence instead of a second incident.
  Deleted with its organisation.
- `admin_incident_events`: its history, append-only (a trigger refuses any
  change but forgetting an admin deleted); each fact read once.
- `admin_notifications`: what the team is told, once each; and
  `admin_notification_reads`, read by each admin on their own.
- `incidents:read` granted to every role, `incidents:write` to Operations and
  Support, as the roles stand (the Super Admin may take them back).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b1323b797096"
down_revision: str | None = "658e6460a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READ = "incidents:read"
WRITE = "incidents:write"
GRANTS = [
    ("operations", READ),
    ("support", READ),
    ("finance", READ),
    ("operations", WRITE),
    ("support", WRITE),
]


def upgrade() -> None:
    op.create_table(
        "admin_incidents",
        sa.Column("number", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("for_workspace_id", sa.UUID(), nullable=True),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=15), nullable=False),
        sa.Column("fingerprint", sa.String(length=300), nullable=False),
        sa.Column("technical_id", sa.String(length=200), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recurring", sa.Boolean(), nullable=False),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_id", sa.UUID(), nullable=True),
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
            "category IN ('intention_failed', 'agent_failed', 'api_error', 'integration_disconnected', 'sync_failed', 'credits', 'payment_failed', 'platform')",
            name=op.f("ck_admin_incidents_category"),
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low')",
            name=op.f("ck_admin_incidents_severity"),
        ),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'resolved', 'closed')",
            name=op.f("ck_admin_incidents_status"),
        ),
        sa.CheckConstraint("occurrences >= 1", name=op.f("ck_admin_incidents_occurrences")),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["admin_accounts.id"],
            name=op.f("fk_admin_incidents_assignee_id_admin_accounts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["for_workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_admin_incidents_for_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["previous_id"],
            ["admin_incidents.id"],
            name=op.f("fk_admin_incidents_previous_id_admin_incidents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_incidents")),
        sa.UniqueConstraint("number", name=op.f("uq_admin_incidents_number")),
    )
    op.create_index(
        "ix_admin_incidents_status_seen",
        "admin_incidents",
        ["status", "last_seen_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_incidents_workspace_seen",
        "admin_incidents",
        ["for_workspace_id", "last_seen_at"],
        unique=False,
    )
    op.create_index(
        "uq_admin_incidents_open_fingerprint",
        "admin_incidents",
        ["fingerprint"],
        unique=True,
        postgresql_where="status IN ('new', 'in_progress')",
    )
    op.create_table(
        "admin_incident_events",
        sa.Column("incident_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admin_id", sa.UUID(), nullable=True),
        sa.Column("admin_email", sa.String(length=320), nullable=True),
        sa.Column("dedupe_key", sa.String(length=300), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            "kind IN ('opened', 'occurred', 'recurring', 'assigned', 'status', 'note', 'auto_resolved')",
            name=op.f("ck_admin_incident_events_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_accounts.id"],
            name=op.f("fk_admin_incident_events_admin_id_admin_accounts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["admin_incidents.id"],
            name=op.f("fk_admin_incident_events_incident_id_admin_incidents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_incident_events")),
        sa.UniqueConstraint("dedupe_key", name="uq_admin_incident_events_dedupe"),
    )
    op.create_index(
        "ix_admin_incident_events_incident_at",
        "admin_incident_events",
        ["incident_id", "at"],
        unique=False,
    )
    op.create_table(
        "admin_notifications",
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("for_workspace_id", sa.UUID(), nullable=True),
        sa.Column("incident_id", sa.UUID(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            "kind IN ('critical_incident', 'payment_failed', 'integration_disconnected', 'repeated_errors', 'capacity_near_limit', 'abnormal_consumption')",
            name=op.f("ck_admin_notifications_kind"),
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low')",
            name=op.f("ck_admin_notifications_severity"),
        ),
        sa.ForeignKeyConstraint(
            ["for_workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_admin_notifications_for_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["admin_incidents.id"],
            name=op.f("fk_admin_notifications_incident_id_admin_incidents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_notifications")),
        sa.UniqueConstraint("dedupe_key", name="uq_admin_notifications_dedupe"),
    )
    op.create_index("ix_admin_notifications_at", "admin_notifications", ["at"], unique=False)
    op.create_table(
        "admin_notification_reads",
        sa.Column("notification_id", sa.UUID(), nullable=False),
        sa.Column("admin_id", sa.UUID(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
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
            name=op.f("fk_admin_notification_reads_admin_id_admin_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["admin_notifications.id"],
            name=op.f("fk_admin_notification_reads_notification_id_admin_notifications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_notification_reads")),
        sa.UniqueConstraint("notification_id", "admin_id", name="uq_admin_notification_reads"),
    )
    op.create_index(
        op.f("ix_admin_notification_reads_admin_id"),
        "admin_notification_reads",
        ["admin_id"],
        unique=False,
    )

    # The history is never changed, but to forget an admin whose account went.
    op.execute(
        """
        CREATE FUNCTION admin_incident_events_append_only() RETURNS trigger AS $$
        BEGIN
            IF NEW.admin_id IS NULL AND OLD.admin_id IS NOT NULL
               AND (NEW.incident_id, NEW.kind, NEW.at, NEW.admin_email, NEW.dedupe_key, NEW.detail)
                   IS NOT DISTINCT FROM
                   (OLD.incident_id, OLD.kind, OLD.at, OLD.admin_email, OLD.dedupe_key, OLD.detail)
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'admin_incident_events is append-only: its history is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_incident_events_append_only
        BEFORE UPDATE ON admin_incident_events
        FOR EACH ROW EXECUTE FUNCTION admin_incident_events_append_only()
        """
    )
    table = sa.table(
        "admin_role_permissions",
        sa.column("id", sa.UUID()),
        sa.column("role", sa.String()),
        sa.column("permission", sa.String()),
        sa.column("granted_by", sa.String()),
    )
    op.bulk_insert(
        table,
        [
            {"id": uuid.uuid4(), "role": role, "permission": permission, "granted_by": "LEKA-556"}
            for role, permission in GRANTS
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM admin_role_permissions WHERE permission IN (:read, :write)"
        ).bindparams(read=READ, write=WRITE)
    )
    op.execute("DROP TRIGGER admin_incident_events_append_only ON admin_incident_events")
    op.execute("DROP FUNCTION admin_incident_events_append_only()")
    op.drop_index(
        op.f("ix_admin_notification_reads_admin_id"), table_name="admin_notification_reads"
    )
    op.drop_table("admin_notification_reads")
    op.drop_index("ix_admin_notifications_at", table_name="admin_notifications")
    op.drop_table("admin_notifications")
    op.drop_index("ix_admin_incident_events_incident_at", table_name="admin_incident_events")
    op.drop_table("admin_incident_events")
    op.drop_index(
        "uq_admin_incidents_open_fingerprint",
        table_name="admin_incidents",
        postgresql_where="status IN ('new', 'in_progress')",
    )
    op.drop_index("ix_admin_incidents_workspace_seen", table_name="admin_incidents")
    op.drop_index("ix_admin_incidents_status_seen", table_name="admin_incidents")
    op.drop_table("admin_incidents")
