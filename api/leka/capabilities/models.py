"""Tables owned by the capabilities module.

The catalogue's history (LEKA-393), LEKA's and no customer's: every version
of every capability ever registered — what it was (its fingerprint), where
it stood in its lifecycle — and every event of that history, append-only.
And each workspace's say on them: enabled or not, and its people's
favourites.

Agents themselves are never stored here. They are files in agents/
(architecture rule 8); what is kept is that they were registered, as what.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class CapabilityRegistration(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One version of one capability, as it was registered. LEKA's
    catalogue, not a tenant's: no workspace_id (test_tenant_isolation)."""

    __tablename__ = "capability_registrations"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_capability_registrations_key_version"),
        Index("ix_capability_registrations_key", "key"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(12), nullable=False)
    # What it is and does, hashed (definition.fingerprint).
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # What the catalogue says of it — an agent's instructions only hashed.
    definition: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lifecycle_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When a later version took its place.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CapabilityEvent(Base, UUIDPrimaryKeyMixin):
    """One thing that happened in the catalogue: registered, moved in its
    lifecycle, superseded, refused — when, why. Append-only: the database
    refuses to change one."""

    __tablename__ = "capability_events"
    __table_args__ = (Index("ix_capability_events_key_at", "key", "at"),)

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    # registered, lifecycle_changed, superseded, refused
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    from_lifecycle: Mapped[str | None] = mapped_column(String(12), nullable=True)
    to_lifecycle: Mapped[str | None] = mapped_column(String(12), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class WorkspaceCapability(Base, WorkspaceScopedMixin):
    """A workspace's say on one capability: enabled, or not and why. None:
    enabled."""

    __tablename__ = "workspace_capabilities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_workspace_capabilities_key"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CapabilityFavourite(Base, WorkspaceScopedMixin):
    """A capability a person keeps at hand: « Mes capacités »."""

    __tablename__ = "capability_favourites"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "key", name="uq_capability_favourites_key"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
