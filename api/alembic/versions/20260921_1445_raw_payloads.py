"""raw_payloads: metadata for the bytes we keep outside the database.

Revision ID: 67406715fb5e
Revises: c4d81b6f2e70
Created: 2026-09-21

LEKA-332. One table, and it is half of a pair.

**The bytes are not here.** A GitHub API response, a Datadog log export, a
raw Confluence page: these are the largest volume LEKA handles and the
shortest-lived. In PostgreSQL they would swell every backup, lengthen every
restore, and make retention expensive twice over — paying to keep them and
paying again to delete them. So the payload goes to an object store and this
row holds everything we know about it: where it came from, how big it is,
what it hashes to, and when it stops being ours to keep. See
docs/adr/010-object-storage.md.

**The composite foreign key is the house pattern**, the same one `entities`
uses since migration 001. (workspace_id, source_id) references
(sources.workspace_id, sources.id) rather than sources.id alone, so a row
belonging to one workspace cannot point at another workspace's source. The
database refuses it; nothing has to remember.

**No unique constraint, deliberately.** This table grows without bound and
will be partitioned by fetched_at when it has to be. PostgreSQL requires
every unique constraint on a partitioned table to include the partition key,
so a unique index added today is a migration blocked tomorrow. The uuid
inside each object key makes collisions a non-problem without one. The
threshold that will make us partition is written down in ADR 010 as a number,
not as "when it becomes necessary".

**Deleting a row does not delete the object.** ON DELETE CASCADE removes
these rows when a workspace goes; the bytes in the store are untouched by it.
That is handled explicitly — a prefix purge when a workspace is erased, and a
reconciliation sweep that catches whatever the purge missed. Without both, a
deleted customer's data would stay with us for ever, which is a GDPR failure
and a bill nobody can explain.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "67406715fb5e"
down_revision: str | None = "c4d81b6f2e70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_payloads",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        # Where the bytes are:
        # {workspace}/{source}/{yyyy}/{mm}/{dd}/{uuid}.{ext}
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=False),
        # BigInteger: a 2 GB log export is not a strange thing for a connector
        # to produce, and int4 stops at 2 147 483 647.
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        # SHA-256, measured by the store while writing. 64 hex characters.
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        # The future partition key. Never rewritten.
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        # NOT NULL: a nullable expiry reads as "keep for ever", and a
        # retention policy must not have a quiet way to opt out of it.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # A payload withdrawn before its expiry. Out of every read at once;
        # the sweep removes the object and then the row.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_raw_payloads_size_not_negative")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_raw_payloads_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_raw_payloads_workspace_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_payloads")),
    )
    # Rule 2: every workspace-scoped table indexes workspace_id. Without it,
    # isolation costs a sequential scan per customer.
    op.create_index(
        op.f("ix_raw_payloads_workspace_id"),
        "raw_payloads",
        ["workspace_id"],
    )
    # What the background loop asks for: one source, most recent first.
    op.create_index(
        "ix_raw_payloads_workspace_source_fetched",
        "raw_payloads",
        ["workspace_id", "source_id", "fetched_at"],
    )
    # What the retention sweep asks for, across every tenant at once. Without
    # it that is a full scan of the largest table in the product, every hour.
    op.create_index("ix_raw_payloads_expires_at", "raw_payloads", ["expires_at"])
    # Finding the copies of one payload: the same content collected again, or
    # a stored object that no longer matches what we recorded.
    op.create_index(
        "ix_raw_payloads_checksum",
        "raw_payloads",
        ["workspace_id", "checksum_sha256"],
    )


def downgrade() -> None:
    """Drop the table.

    THE OBJECTS ARE NOT DROPPED. Nothing in a database migration can reach
    the object store, and pretending otherwise here would be worse than
    saying it plainly: downgrading this revision leaves every stored payload
    in place with nothing left to describe it. Purge the store separately, or
    upgrade again and let the reconciliation sweep find them.
    """
    op.drop_index("ix_raw_payloads_checksum", table_name="raw_payloads")
    op.drop_index("ix_raw_payloads_expires_at", table_name="raw_payloads")
    op.drop_index("ix_raw_payloads_workspace_source_fetched", table_name="raw_payloads")
    op.drop_index(op.f("ix_raw_payloads_workspace_id"), table_name="raw_payloads")
    op.drop_table("raw_payloads")
