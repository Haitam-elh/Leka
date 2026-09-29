"""Webhook deliveries: what webhook sources received.

Revision ID: 6c3e8a1f2d94
Revises: 4d7e2a9c1b63
Created: 2026-09-29

LEKA-350. One new table; and `sync_runs.trigger` accepts `webhook`.

`webhook_deliveries` holds one row per signed delivery a `custom_webhook`
source received: `pending`, with its body, until the source's next pass
stores what it holds; then `stored`, `ignored` or `rejected`, its body let
go, kept 30 days as the source's log of deliveries. Deleted with its source.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "6c3e8a1f2d94"
down_revision: str | None = "4d7e2a9c1b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("delivery_id", sa.String(length=200), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("resource", sa.String(length=40), nullable=True),
        sa.Column("records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("gone", sa.Integer(), server_default="0", nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'stored', 'ignored', 'rejected')",
            name=op.f("ck_webhook_deliveries_status"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0 AND records >= 0 AND gone >= 0",
            name=op.f("ck_webhook_deliveries_counts_not_negative"),
        ),
        sa.CheckConstraint(
            "status = 'pending' OR body IS NULL",
            name=op.f("ck_webhook_deliveries_body_only_while_pending"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_webhook_deliveries_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_webhook_deliveries_workspace_source",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["sync_runs.id"],
            ondelete="SET NULL",
            name=op.f("fk_webhook_deliveries_run_id_sync_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    op.create_index(
        op.f("ix_webhook_deliveries_workspace_id"), "webhook_deliveries", ["workspace_id"]
    )
    op.create_index(
        "ix_webhook_deliveries_source_received_at",
        "webhook_deliveries",
        ["source_id", "received_at"],
    )
    op.create_index(
        "ix_webhook_deliveries_pending",
        "webhook_deliveries",
        ["source_id", "received_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.drop_constraint(op.f("ck_sync_runs_trigger"), "sync_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_runs_trigger"),
        "sync_runs",
        "trigger IN ('activation', 'schedule', 'manual', 'settings', 'webhook')",
    )


def downgrade() -> None:
    # A pass a delivery started was, before this revision, a scheduled one.
    op.execute("UPDATE sync_runs SET trigger = 'schedule' WHERE trigger = 'webhook'")
    op.drop_constraint(op.f("ck_sync_runs_trigger"), "sync_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_runs_trigger"),
        "sync_runs",
        "trigger IN ('activation', 'schedule', 'manual', 'settings')",
    )
    op.drop_index("ix_webhook_deliveries_pending", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_source_received_at", table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_workspace_id"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
