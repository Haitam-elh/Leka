"""What the notification centre keeps (LEKA-476).

One row per fact told, never one per person: who may see it is said by its
audience — a person (an intention's asker), a permission (who may approve,
who manages sources, who pays), both (either sees it), or neither (every
member) — and judged when it is read, against the reader's permissions as
they are then. Whether a person has read it is theirs, a row of its own.

The same fact never twice: its key is the fact's own identity — an event's
id, an alert and what happened to it — unique in its workspace.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin

CATEGORIES = ("intention", "source", "monitoring", "billing", "agent", "workspace")
SEVERITIES = ("info", "success", "warning", "critical")


def _among(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Notification(Base, WorkspaceScopedMixin):
    __tablename__ = "notifications"
    # About an entity: hidden with it from who may not see it (LEKA-402).
    __entity_refs__ = ("entity_id",)
    __table_args__ = (
        UniqueConstraint("workspace_id", "event_key", name="uq_notifications_event"),
        CheckConstraint(_among("category", CATEGORIES), name="category"),
        CheckConstraint(_among("severity", SEVERITIES), name="severity"),
        Index("ix_notifications_workspace_occurred", "workspace_id", "occurred_at"),
    )

    # The fact's own identity: told once.
    event_key: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    # What its words are made of: a title, a name, a plan, a share — never
    # the words themselves, said in the reader's language.
    params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Where it leads, in the application: a path, never an address elsewhere.
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Who may see it: this person, or whoever holds this permission — both
    # set, either; neither, every member.
    audience_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    audience_permission: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # When it happened, as its source system says.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NotificationSeen(Base, WorkspaceScopedMixin):
    """A person has read a notification: when."""

    __tablename__ = "notification_reads"
    __table_args__ = (
        UniqueConstraint("notification_id", "user_id", name="uq_notification_reads_person"),
        Index("ix_notification_reads_person", "workspace_id", "user_id"),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NotificationPreference(Base, WorkspaceScopedMixin):
    """What a person does not want told in the centre — by category. In the
    application only: the monitoring alerts' e-mails are their own."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_notification_preferences_person"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    muted: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")


class NotificationCursor(Base, WorkspaceScopedMixin):
    """How far the facts of one family were read into notifications — and,
    when reading them failed, why and when: said, never silent."""

    __tablename__ = "notification_cursors"
    __table_args__ = (
        UniqueConstraint("workspace_id", "family", name="uq_notification_cursors_family"),
    )

    family: Mapped[str] = mapped_column(String(20), nullable=False)
    read_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure: Mapped[str | None] = mapped_column(String(500), nullable=True)
