"""Intentions: what was asked, where it stands, what happened to it.

Revision ID: 3c8e5a1f7d92
Revises: 9a5c3e7f1b20
Created: 2026-10-07

LEKA-384. An intention is kept from the moment someone asks
(`intentions`): its words, its scope, its status in its lifecycle. Every
change is an event of its history (`intention_events`), numbered — and the
database refuses to change one: a trigger, so the history can be audited.
What it rests on and what came of it is linked (`intention_links`).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3c8e5a1f7d92"
down_revision: str | None = "9a5c3e7f1b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "submitted",
    "analysing",
    "awaiting_decision",
    "approved",
    "scheduled",
    "executing",
    "verifying",
    "completed",
    "rejected",
    "failed",
    "cancelled",
)
EVENT_KINDS = ("created", "moved", "linked", "unlinked", "archived", "restored")
LINK_KINDS = ("context", "finding", "entity", "decision", "action", "outcome")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _table(name: str, *columns: sa.Column[object], others: Sequence[object] = ()) -> None:
    """A workspace's table, as leka.db's mixin makes them."""
    op.create_table(
        name,
        *columns,
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
        *others,
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{name}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    op.create_index(op.f(f"ix_{name}_workspace_id"), name, ["workspace_id"])


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def _intention(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "intention_id"],
        ["intentions.workspace_id", "intentions.id"],
        name=f"fk_{table}_intention",
        ondelete="CASCADE",
    )


def upgrade() -> None:
    _table(
        "intentions",
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=True),
        _jsonb("scope", "{}"),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("context_id", sa.UUID(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("events_count", sa.Integer(), server_default="0", nullable=False),
        others=(
            sa.UniqueConstraint("workspace_id", "id", name="uq_intentions_workspace_id_id"),
            sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_intentions_status")),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["users.id"],
                name=op.f("fk_intentions_created_by_users"),
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["context_id"],
                ["contexts.id"],
                name=op.f("fk_intentions_context_id_contexts"),
                ondelete="SET NULL",
            ),
        ),
    )
    for name, columns in (
        ("updated", ["workspace_id", "updated_at"]),
        ("status", ["workspace_id", "status"]),
        ("created_by", ["workspace_id", "created_by"]),
    ):
        op.create_index(f"ix_intentions_workspace_{name}", "intentions", columns)

    _table(
        "intention_events",
        sa.Column("intention_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=True),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=True),
        sa.Column("actor", sa.String(length=10), nullable=False),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        _jsonb("detail", "{}"),
        others=(
            _intention("intention_events"),
            sa.UniqueConstraint("intention_id", "sequence", name="uq_intention_events_sequence"),
            sa.CheckConstraint(_in("kind", EVENT_KINDS), name=op.f("ck_intention_events_kind")),
            sa.CheckConstraint(
                _in("actor", ("person", "system")), name=op.f("ck_intention_events_actor")
            ),
            sa.CheckConstraint(
                "(kind = 'moved') = (to_status IS NOT NULL)",
                name=op.f("ck_intention_events_moved_says_where"),
            ),
            sa.ForeignKeyConstraint(
                ["by"], ["users.id"], name=op.f("fk_intention_events_by_users"), ondelete="SET NULL"
            ),
        ),
    )
    op.create_index(
        "ix_intention_events_intention", "intention_events", ["intention_id", "sequence"]
    )
    # The history is append-only, and the database says so: an event is
    # never changed. Deleting stays possible — an intention's events go with
    # it, a workspace's with the workspace — and the user who did it may be
    # forgotten (`by` set null when the user is deleted, a GDPR erasure).
    op.execute(
        """
        CREATE FUNCTION intention_events_append_only() RETURNS trigger AS $$
        BEGIN
            -- The one change allowed: who did it forgotten, with the user.
            IF NEW."by" IS NULL AND to_jsonb(NEW) - 'by' = to_jsonb(OLD) - 'by' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'intention_events is append-only: an event is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER intention_events_append_only
        BEFORE UPDATE ON intention_events
        FOR EACH ROW EXECUTE FUNCTION intention_events_append_only()
        """
    )

    _table(
        "intention_links",
        sa.Column("intention_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ref_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        _jsonb("detail", "{}"),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_by", sa.UUID(), nullable=True),
        others=(
            _intention("intention_links"),
            sa.UniqueConstraint("intention_id", "kind", "ref_id", name="uq_intention_links_ref"),
            sa.CheckConstraint(_in("kind", LINK_KINDS), name=op.f("ck_intention_links_kind")),
            sa.ForeignKeyConstraint(
                ["linked_by"],
                ["users.id"],
                name=op.f("fk_intention_links_linked_by_users"),
                ondelete="SET NULL",
            ),
        ),
    )
    op.create_index("ix_intention_links_ref", "intention_links", ["workspace_id", "kind", "ref_id"])


def downgrade() -> None:
    op.drop_table("intention_links")
    op.execute("DROP TRIGGER intention_events_append_only ON intention_events")
    op.execute("DROP FUNCTION intention_events_append_only()")
    op.drop_table("intention_events")
    op.drop_table("intentions")
