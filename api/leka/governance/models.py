"""Tables owned by the governance module.

The audit trail. Append-only by intent: a row is written when something
happens and never updated, because an audit log that can be edited is not
an audit log.

LEKA-402: the entities an admin restricted, and every access decision worth
keeping — each refusal, each write or run allowed — append-only, the
database refusing to change one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin


class EntityRestriction(Base, WorkspaceScopedMixin):
    """An entity of the company model only the workspace's administrators
    see (LEKA-402): hidden everywhere from anyone else — the entity, what
    refers to it — said why, by whom, since when."""

    __tablename__ = "entity_restrictions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "entity_id", name="uq_entity_restrictions_entity"),
    )

    # No foreign key: governance sits below knowledge; an entity removed
    # from the model leaves a restriction that hides nothing.
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    restricted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    restricted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessDecision(Base, WorkspaceScopedMixin):
    """One access decision kept (LEKA-402): who asked to do what, on what,
    whether it was allowed, by which rule and why — every refusal, every
    write and every run allowed. Append-only: the database refuses to change
    one."""

    __tablename__ = "access_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('allow', 'deny')", name="decision"),
        Index("ix_access_decisions_workspace_at", "workspace_id", "at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # A permission (workspace:update…) or an action under one (agent:run…).
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    permission: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision: Mapped[str] = mapped_column(String(5), nullable=False)
    # workspace, role, owner, restriction — and the reason it gave.
    rule: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    # The role it was decided for, then.
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    route: Mapped[str | None] = mapped_column(String(200), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
