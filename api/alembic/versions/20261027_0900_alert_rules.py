"""The alerts a person sets on Mon environnement (LEKA-477): on what, for
which troubles, how bad, after how long, how often, to whom and how — and
each telling kept, sent or failed, once per rule, alert, channel, recipient
and round.

Revision ID: adee2d9b1cf5
Revises: d5f1b8c3a940
Created: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "adee2d9b1cf5"
down_revision: str | None = "d5f1b8c3a940"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitoring_alert_rules",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("subject_type", sa.String(length=10), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("subject_name", sa.String(length=300), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("confirm_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("repeat_hours", sa.Integer(), nullable=True),
        sa.Column("channels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
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
            "severity IN ('high', 'medium', 'low')", name=op.f("ck_monitoring_alert_rules_severity")
        ),
        sa.CheckConstraint(
            "subject_type IN ('entity', 'source')",
            name=op.f("ck_monitoring_alert_rules_subject_type"),
        ),
        sa.CheckConstraint(
            "confirm_minutes >= 0", name=op.f("ck_monitoring_alert_rules_confirm_minutes")
        ),
        sa.CheckConstraint(
            "repeat_hours IS NULL OR repeat_hours > 0",
            name=op.f("ck_monitoring_alert_rules_repeat_hours"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_monitoring_alert_rules_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monitoring_alert_rules")),
    )
    op.create_index(
        "ix_monitoring_alert_rules_workspace_enabled",
        "monitoring_alert_rules",
        ["workspace_id", "enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_monitoring_alert_rules_workspace_id"),
        "monitoring_alert_rules",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "monitoring_alert_deliveries",
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column("alert_id", sa.UUID(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("round", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
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
            "channel IN ('in_app', 'email', 'sms', 'whatsapp', 'slack', 'teams', 'discord')",
            name=op.f("ck_monitoring_alert_deliveries_channel"),
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'failed')", name=op.f("ck_monitoring_alert_deliveries_status")
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["monitoring_alerts.id"],
            name=op.f("fk_monitoring_alert_deliveries_alert_id_monitoring_alerts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["monitoring_alert_rules.id"],
            name=op.f("fk_monitoring_alert_deliveries_rule_id_monitoring_alert_rules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_monitoring_alert_deliveries_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monitoring_alert_deliveries")),
    )
    op.create_index(
        "ix_monitoring_alert_deliveries_rule_at",
        "monitoring_alert_deliveries",
        ["rule_id", "at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_monitoring_alert_deliveries_workspace_id"),
        "monitoring_alert_deliveries",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_monitoring_alert_deliveries_once",
        "monitoring_alert_deliveries",
        ["rule_id", "alert_id", "channel", "recipient", "round"],
        unique=True,
        postgresql_where=sa.text("alert_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("monitoring_alert_deliveries")
    op.drop_table("monitoring_alert_rules")
