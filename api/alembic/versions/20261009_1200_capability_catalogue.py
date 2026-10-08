"""Capability catalogue: what LEKA can do, every version, and each workspace's say.

Revision ID: 6b1e9d4c2f73
Revises: 2d9f6b3e8a51
Created: 2026-10-09

LEKA-393. The catalogue's history, LEKA's and no customer's: every version of
every capability registered — what it was, where it stood in its lifecycle
(`capability_registrations`) — and every event of that history, append-only
(`capability_events`: the database refuses to change one). Each workspace's
say: a capability enabled or not, and why (`workspace_capabilities`); what its
people keep at hand (`capability_favourites`).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "6b1e9d4c2f73"
down_revision: str | None = "2d9f6b3e8a51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capability_events",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("from_lifecycle", sa.String(length=12), nullable=True),
        sa.Column("to_lifecycle", sa.String(length=12), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_events")),
    )
    op.create_index("ix_capability_events_key_at", "capability_events", ["key", "at"], unique=False)
    op.create_table(
        "capability_registrations",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("lifecycle", sa.String(length=12), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lifecycle_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_registrations")),
        sa.UniqueConstraint("key", "version", name="uq_capability_registrations_key_version"),
    )
    op.create_index(
        "ix_capability_registrations_key", "capability_registrations", ["key"], unique=False
    )
    op.create_table(
        "capability_favourites",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_capability_favourites_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_capability_favourites_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_favourites")),
        sa.UniqueConstraint("workspace_id", "user_id", "key", name="uq_capability_favourites_key"),
    )
    op.create_index(
        op.f("ix_capability_favourites_workspace_id"),
        "capability_favourites",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "workspace_capabilities",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name=op.f("fk_workspace_capabilities_changed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_capabilities_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_capabilities")),
        sa.UniqueConstraint("workspace_id", "key", name="uq_workspace_capabilities_key"),
    )
    op.create_index(
        op.f("ix_workspace_capabilities_workspace_id"),
        "workspace_capabilities",
        ["workspace_id"],
        unique=False,
    )
    # The catalogue's history is append-only, and the database says so.
    op.execute(
        """
        CREATE FUNCTION capability_events_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'capability_events is append-only: an event is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER capability_events_append_only
        BEFORE UPDATE ON capability_events
        FOR EACH ROW EXECUTE FUNCTION capability_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER capability_events_append_only ON capability_events")
    op.execute("DROP FUNCTION capability_events_append_only()")
    op.drop_index(
        op.f("ix_workspace_capabilities_workspace_id"), table_name="workspace_capabilities"
    )
    op.drop_table("workspace_capabilities")
    op.drop_index(op.f("ix_capability_favourites_workspace_id"), table_name="capability_favourites")
    op.drop_table("capability_favourites")
    op.drop_index("ix_capability_registrations_key", table_name="capability_registrations")
    op.drop_table("capability_registrations")
    op.drop_index("ix_capability_events_key_at", table_name="capability_events")
    op.drop_table("capability_events")
