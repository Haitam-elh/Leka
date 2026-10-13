"""Alerts on the environment: a thing or a source in trouble, from when it
opened to when a signal verified it ended.

Revision ID: 3dee77e03bf8
Revises: 8b3f1d6a2c47
Created: 2026-10-21

`monitoring_alerts` (LEKA-442): one open alert per thing and family of
trouble (a partial unique index) — the same trouble seen again moves its
last sighting; its certainty follows the data; only a fresh signal resolves
it. Opened only for a workspace whose plan watches proactively.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3dee77e03bf8"
down_revision: str | None = "8b3f1d6a2c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitoring_alerts",
        sa.Column("subject_type", sa.String(length=10), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("subject_name", sa.String(length=300), nullable=False),
        sa.Column("family", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("certainty", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="open", nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("resolution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "notified", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
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
            "subject_type IN ('entity', 'source')", name=op.f("ck_monitoring_alerts_subject_type")
        ),
        sa.CheckConstraint(
            "kind IN ('unavailable', 'degraded', 'source_failing')",
            name=op.f("ck_monitoring_alerts_kind"),
        ),
        sa.CheckConstraint(
            "severity IN ('high', 'medium', 'low')", name=op.f("ck_monitoring_alerts_severity")
        ),
        sa.CheckConstraint(
            "certainty IN ('confirmed', 'suspected', 'unverified')",
            name=op.f("ck_monitoring_alerts_certainty"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'closed')", name=op.f("ck_monitoring_alerts_status")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_monitoring_alerts_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monitoring_alerts")),
    )
    op.create_index(
        op.f("ix_monitoring_alerts_workspace_id"), "monitoring_alerts", ["workspace_id"]
    )
    op.create_index(
        "ix_monitoring_alerts_workspace_status",
        "monitoring_alerts",
        ["workspace_id", "status", "opened_at"],
    )
    op.create_index(
        "uq_monitoring_alerts_open",
        "monitoring_alerts",
        ["workspace_id", "subject_id", "family"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_table("monitoring_alerts")
