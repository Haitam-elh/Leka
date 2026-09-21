"""Tables owned by the ingestion module.

Ingestion writes entities and relationships, but it does not own them —
leka.knowledge does. What ingestion owns is the record of its own work: what
ran, over which source, what it produced, what it could not parse.

A failed parse is data, not an exception to swallow. It is how we find out a
vendor changed a payload shape.

`raw_payloads` is the first of those tables. It is the row half of the split
described in docs/adr/010-object-storage.md: the bytes live in the object
store, and this is everything we know about them — where they came from, how
big they are, what they hash to, and when they stop being ours to keep.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin


class RawPayload(Base, WorkspaceScopedMixin):
    """One thing we fetched from a customer system, kept outside the database.

    THE BYTES ARE NOT HERE. `object_key` points into the object store; this
    row is the metadata and the lifecycle. Two reasons, both operational:
    payloads are the largest volume and the shortest-lived thing LEKA holds,
    so keeping them in PostgreSQL would swell every backup and lengthen every
    restore — and deleting them, which we must do on a schedule, would mean
    rewriting table pages rather than dropping objects.

    NO UNIQUE CONSTRAINT, anywhere, on purpose. This table grows without
    bound and will be partitioned by `fetched_at` one day; PostgreSQL
    requires every unique constraint on a partitioned table to include the
    partition key, so a unique index written today is a migration blocked
    tomorrow. The uuid inside each object key makes collisions a non-problem
    without one.
    """

    __tablename__ = "raw_payloads"
    __table_args__ = (
        # The house pattern, the same one entities uses: a composite foreign
        # key through workspace_id. A single-column reference to sources.id
        # would let one workspace's payload point at another workspace's
        # source — the database itself refuses that here.
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_raw_payloads_workspace_source",
            ondelete="CASCADE",
        ),
        # What the background loop asks for: this source, most recent first.
        Index(
            "ix_raw_payloads_workspace_source_fetched", "workspace_id", "source_id", "fetched_at"
        ),
        # What the retention sweep asks for, across every tenant: what has
        # outlived its policy. Without this it is a full scan of the largest
        # table in the product, every hour, for ever.
        Index("ix_raw_payloads_expires_at", "expires_at"),
        # Finding the copies of one payload: the same content fetched again,
        # or a stored object that no longer matches what we recorded.
        Index("ix_raw_payloads_checksum", "workspace_id", "checksum_sha256"),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Where the bytes are: {workspace}/{source}/{yyyy}/{mm}/{dd}/{uuid}.{ext}
    # See leka.platform.storage.object_key for why that shape.
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)

    content_type: Mapped[str] = mapped_column(String(200), nullable=False)

    # BigInteger, not Integer. A 2 GB log export is not a strange thing for a
    # connector to produce, and int4 stops at 2 147 483 647 bytes.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # SHA-256 of the payload, measured while it was written. 64 hex
    # characters. Two jobs: telling the same payload from a changed one when
    # we re-sync a repository we already have, and catching an object that
    # has silently rotted before we analyse it and answer a customer with
    # something untrue.
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # When it was collected. This is the future partition key, so it is
    # NOT NULL and never rewritten.
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # When the retention policy says this stops being ours to keep. NOT NULL:
    # a nullable expiry reads as "keep for ever", and the one thing a
    # retention policy must never have is a quiet way to opt out of it.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Set when a payload is withdrawn before its expiry — a source
    # disconnected, a customer asking for one thing to go. The sweep removes
    # the object and then the row; until it runs, this is what keeps the row
    # out of every read.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
