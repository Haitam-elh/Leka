"""events: the outbox of the background loop.

Revision ID: 87a4e899df19
Revises: 67406715fb5e
Created: 2026-09-21

LEKA-334. One table; docs/adr/012-events-and-job-runs.md says why.

**events** belongs to a workspace and follows the house pattern: workspace_id
NOT NULL with a foreign key, a composite unique (workspace_id, id) for other
tables to reference, and an index on workspace_id. It is an outbox: a row is
written in the same transaction as the change that caused it, so an event
exists if and only if the change does, and a dispatcher turns pending rows into
job runs later. Redis is never on the path of a transaction.

**The dedupe key is a constraint, not a check.** UNIQUE (workspace_id,
dedupe_key) is what turns a webhook delivered twice into one event: a check in
application code has a race between the check and the write, and a constraint
does not. It is per workspace so two customers producing the same key cannot
learn about each other, and NULL keys are distinct, so an event with no key has
nothing to be a duplicate of.

**Status is text with a CHECK**, not a PostgreSQL ENUM (ADR 006): adding a
value to a native ENUM needs its own migration, and this list will move.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "87a4e899df19"
down_revision: str | None = "67406715fb5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("dispatch_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("runs_created_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'runs_created', 'failed')", name=op.f("ck_events_status")
        ),
        sa.CheckConstraint("length(type) > 0", name=op.f("ck_events_type_not_empty")),
        sa.CheckConstraint(
            "dispatch_attempts >= 0", name=op.f("ck_events_dispatch_attempts_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_events_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_events_workspace_id_id"),
        sa.UniqueConstraint("workspace_id", "dedupe_key", name="uq_events_workspace_dedupe_key"),
    )
    # Rule 2: every workspace-scoped table indexes workspace_id.
    op.create_index(op.f("ix_events_workspace_id"), "events", ["workspace_id"])
    # The dispatcher: what is pending, oldest first, across every workspace.
    # Retention: what has settled and is older than N days.
    op.create_index("ix_events_status_created_at", "events", ["status", "created_at"])


def downgrade() -> None:
    """Drop the table.

    Nothing outside the database is touched. A job already on the RQ queue
    keeps existing there; drain the queue first if that matters.
    """
    op.drop_index("ix_events_status_created_at", table_name="events")
    op.drop_index(op.f("ix_events_workspace_id"), table_name="events")
    op.drop_table("events")
