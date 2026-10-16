"""The notification centre: one notification per fact, its audience, who
read it, what each person mutes, how far each family of facts was read.

Revision ID: d5f1b8c3a940
Revises: 8a4c1e7b2d95
Create Date: 2026-10-16 23:30:00

LEKA-476. `notifications` keeps one row per fact told — unique by the
fact's identity in its workspace, so the same fact is never told twice —
with its audience (a person, a permission, both, or every member) judged as
it is read. `notification_reads`: who read which, when.
`notification_preferences`: the categories a person mutes in the centre.
`notification_cursors`: how far each family was read, and its last failure.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d5f1b8c3a940"
down_revision: str | None = "8a4c1e7b2d95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base(table: str) -> list[sa.Column[object]]:
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


def _keys(table: str) -> list[sa.Constraint]:
    return [
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{table}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("event_key", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column(
            "params", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("audience_user_id", sa.UUID(), nullable=True),
        sa.Column("audience_permission", sa.String(length=40), nullable=True),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        *_base("notifications"),
        sa.CheckConstraint(
            "category IN ('intention', 'source', 'monitoring', 'billing', 'agent', 'workspace')",
            name=op.f("ck_notifications_category"),
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'success', 'warning', 'critical')",
            name=op.f("ck_notifications_severity"),
        ),
        sa.ForeignKeyConstraint(
            ["audience_user_id"],
            ["users.id"],
            name=op.f("fk_notifications_audience_user_id_users"),
            ondelete="CASCADE",
        ),
        *_keys("notifications"),
        sa.UniqueConstraint("workspace_id", "event_key", name="uq_notifications_event"),
    )
    op.create_index(op.f("ix_notifications_workspace_id"), "notifications", ["workspace_id"])
    op.create_index(
        "ix_notifications_workspace_occurred", "notifications", ["workspace_id", "occurred_at"]
    )

    op.create_table(
        "notification_reads",
        sa.Column("notification_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        *_base("notification_reads"),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name=op.f("fk_notification_reads_notification_id_notifications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_reads_user_id_users"),
            ondelete="CASCADE",
        ),
        *_keys("notification_reads"),
        sa.UniqueConstraint("notification_id", "user_id", name="uq_notification_reads_person"),
    )
    op.create_index(
        op.f("ix_notification_reads_workspace_id"), "notification_reads", ["workspace_id"]
    )
    op.create_index(
        "ix_notification_reads_person", "notification_reads", ["workspace_id", "user_id"]
    )

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "muted", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        *_base("notification_preferences"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        *_keys("notification_preferences"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_notification_preferences_person"),
    )
    op.create_index(
        op.f("ix_notification_preferences_workspace_id"),
        "notification_preferences",
        ["workspace_id"],
    )

    op.create_table(
        "notification_cursors",
        sa.Column("family", sa.String(length=20), nullable=False),
        sa.Column("read_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure", sa.String(length=500), nullable=True),
        *_base("notification_cursors"),
        *_keys("notification_cursors"),
        sa.UniqueConstraint("workspace_id", "family", name="uq_notification_cursors_family"),
    )
    op.create_index(
        op.f("ix_notification_cursors_workspace_id"), "notification_cursors", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_table("notification_cursors")
    op.drop_table("notification_preferences")
    op.drop_table("notification_reads")
    op.drop_table("notifications")
