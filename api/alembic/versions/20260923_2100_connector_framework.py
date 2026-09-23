"""Connector framework: lifecycle, health, credentials apart, events.

Revision ID: 5c0f1a7e2b34
Revises: c327b838b263
Created: 2026-09-23

LEKA-344. Four changes to `sources` and two new tables.

1. The credential leaves `sources` for `source_credentials`, with the
   version of the key that wrote it and a masked hint. Existing ciphertext
   is moved as it is: no key is needed to run this migration, so the hint
   of a moved row is a placeholder and its key version "legacy" until the
   next rotation rewrites it.
2. The lifecycle: pending/active/error/disabled becomes
   draft/tested/active/degraded/error/disabled. `pending` meant "created,
   not proven", which is `draft`.
3. `kind` is no longer checked by the database. The registry of
   connectors decides which kinds can be created; a CHECK here made adding
   a connector a migration.
4. Health and sync state, and what the last test found.

`source_events` is the append-only history of each source.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5c0f1a7e2b34"
down_revision: str | None = "c327b838b263"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("github", "jira", "confluence", "aws", "datadog", "slack")
OLD_STATUSES = ("pending", "active", "error", "disabled")
STATUSES = ("draft", "tested", "active", "degraded", "error", "disabled")
HEALTH = ("unknown", "healthy", "degraded", "unhealthy")
SYNC = ("never", "idle", "running", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    # ── 1. credentials apart ─────────────────────────────────────────────────
    op.create_table(
        "source_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(length=32), nullable=False),
        sa.Column("hint", sa.String(length=64), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_source_credentials_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_source_credentials_source",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_credentials")),
        sa.UniqueConstraint("source_id", name="uq_source_credentials_source_id"),
    )
    op.create_index(
        op.f("ix_source_credentials_workspace_id"), "source_credentials", ["workspace_id"]
    )
    op.execute(
        "INSERT INTO source_credentials "
        "(workspace_id, source_id, ciphertext, key_version, hint, rotated_at) "
        "SELECT workspace_id, id, credentials_encrypted, 'legacy', '••••', updated_at "
        "FROM sources WHERE credentials_encrypted IS NOT NULL"
    )
    op.drop_column("sources", "credentials_encrypted")

    # ── 2. the lifecycle ─────────────────────────────────────────────────────
    op.drop_constraint(op.f("ck_sources_status"), "sources", type_="check")
    op.alter_column("sources", "status", server_default=None)
    op.execute("UPDATE sources SET status = 'draft' WHERE status = 'pending'")
    op.alter_column("sources", "status", server_default="draft")
    op.create_check_constraint("status", "sources", _in("status", STATUSES))

    # ── 3. kinds are the registry's business ─────────────────────────────────
    op.drop_constraint(op.f("ck_sources_kind"), "sources", type_="check")

    # ── 4. health, sync, what the last test found ────────────────────────────
    op.add_column(
        "sources", sa.Column("tested_config_fingerprint", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "sources",
        sa.Column("capabilities", postgresql.JSONB(), server_default="[]", nullable=False),
    )
    op.add_column(
        "sources",
        sa.Column("source_metadata", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.add_column(
        "sources",
        sa.Column("health_status", sa.String(length=50), server_default="unknown", nullable=False),
    )
    op.create_check_constraint("health_status", "sources", _in("health_status", HEALTH))
    op.add_column(
        "sources", sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("sources", sa.Column("last_error", postgresql.JSONB(), nullable=True))
    op.add_column(
        "sources",
        sa.Column("sync_status", sa.String(length=50), server_default="never", nullable=False),
    )
    op.create_check_constraint("sync_status", "sources", _in("sync_status", SYNC))
    op.add_column("sources", sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_sources_created_by_users"),
        "sources",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── the history ──────────────────────────────────────────────────────────
    op.create_table(
        "source_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name=op.f("fk_source_events_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_source_events_actor_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_events")),
    )
    op.create_index(op.f("ix_source_events_workspace_id"), "source_events", ["workspace_id"])
    op.create_index(
        "ix_source_events_source_id_created_at", "source_events", ["source_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_events_source_id_created_at", table_name="source_events")
    op.drop_index(op.f("ix_source_events_workspace_id"), table_name="source_events")
    op.drop_table("source_events")

    op.drop_constraint(op.f("fk_sources_created_by_users"), "sources", type_="foreignkey")
    op.drop_column("sources", "created_by")
    op.drop_constraint(op.f("ck_sources_sync_status"), "sources", type_="check")
    op.drop_column("sources", "sync_status")
    op.drop_column("sources", "last_error")
    op.drop_column("sources", "last_health_check_at")
    op.drop_constraint(op.f("ck_sources_health_status"), "sources", type_="check")
    op.drop_column("sources", "health_status")
    op.drop_column("sources", "source_metadata")
    op.drop_column("sources", "capabilities")
    op.drop_column("sources", "tested_config_fingerprint")

    # Only the kinds that existed before can go back under the old check.
    op.create_check_constraint("kind", "sources", _in("kind", KINDS))

    op.drop_constraint(op.f("ck_sources_status"), "sources", type_="check")
    op.alter_column("sources", "status", server_default=None)
    op.execute("UPDATE sources SET status = 'pending' WHERE status IN ('draft', 'tested')")
    op.execute("UPDATE sources SET status = 'error' WHERE status = 'degraded'")
    op.alter_column("sources", "status", server_default="pending")
    op.create_check_constraint("status", "sources", _in("status", OLD_STATUSES))

    op.add_column("sources", sa.Column("credentials_encrypted", sa.LargeBinary(), nullable=True))
    op.execute(
        "UPDATE sources SET credentials_encrypted = c.ciphertext "
        "FROM source_credentials c WHERE c.source_id = sources.id"
    )
    op.drop_index(op.f("ix_source_credentials_workspace_id"), table_name="source_credentials")
    op.drop_table("source_credentials")
