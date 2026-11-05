"""Tables owned by LEKA ADMIN (LEKA-544): LEKA's own, no customer's.

None carries `workspace_id`. They are about LEKA's team and about every
customer at once, so none is scoped; which organisation a row is about, when
it is about one, is `for_workspace_id`, as `job_runs` and `stripe_events`
say it (tests/test_tenant_isolation.py lists them).

`admin_accounts`: the people of LEKA's team who may use LEKA ADMIN — apart
from the customers' `users`, so being a customer, even an owner, never opens
LEKA ADMIN. Their role says what they may do (leka/admin/access.py).

`admin_codes` (LEKA-545): a single-use code sent by email: to an invited
admin, to choose their password; to an admin who forgot theirs, to choose a
new one. Hashed, short-lived, five tries.

`admin_role_permissions` (LEKA-545): what each role may do, as the Super
Admin set it (the defaults of leka/admin/access.py to start with). A Super
Admin's own role is never stored here: it may do everything.

`admin_sessions`: one signed-in device of an admin. The token is hashed; it
is carried as a bearer by the Android app, never as a cookie, so no customer
session can ever stand in for it.

`admin_audit_events`: everything LEKA's team did and read through LEKA
ADMIN — signed in, refused, viewed what a customer wrote, suspended an
organisation, added credits. Append-only: the database refuses to change a
row, except to forget who it was about when an admin or an organisation is
deleted. Kept apart from the customers' audit trail and from its retention.

`admin_idempotency_keys`: the answer to a sensitive operation, kept under
the key the client sent with it, so the same request sent twice is done
once.

`activity_events`: what happened across LEKA, for adoption, activation and
retention — signed up, signed in, active on a day, an organisation created,
a subscription, a payment, an intention, a run, credits consumed, a source
connected. Derived from the tables that already say it (leka/admin/
activity.py), each once by its `dedupe_key`; minimal and never sensitive:
which kind, about which organisation and person, when, and a few figures —
never what anyone wrote.

`activity_watermarks`: how far each source of the activity journal has been
read.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.admin.access import AdminRole
from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

ROLES = tuple(role.value for role in AdminRole)
ACCOUNT_STATUSES = ("invited", "active", "disabled")
CODE_PURPOSES = ("invite", "reset")
OUTCOMES = ("succeeded", "refused", "failed")


def _among(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class AdminAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_accounts"
    __table_args__ = (
        UniqueConstraint("email", name="uq_admin_accounts_email"),
        CheckConstraint(_among("role", ROLES), name="role"),
        CheckConstraint(_among("status", ACCOUNT_STATUSES), name="status"),
    )

    # Lower-cased, always.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # None while invited: the person chooses it with the code they were sent.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    failed_sign_ins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(320), nullable=False)


class AdminSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_sessions"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_admin_sessions_token"),)

    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ip_prefix: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AdminAuditEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_audit_events"
    __table_args__ = (
        CheckConstraint(_among("outcome", OUTCOMES), name="outcome"),
        Index("ix_admin_audit_events_at", "at"),
        Index("ix_admin_audit_events_admin_at", "admin_id", "at"),
        Index("ix_admin_audit_events_workspace_at", "for_workspace_id", "at"),
    )

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True
    )
    # Who it was, as typed at sign-in when no account matched.
    admin_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    for_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    route: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_prefix: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class AdminIdempotencyKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_idempotency_keys"
    __table_args__ = (UniqueConstraint("admin_id", "key", name="uq_admin_idempotency_keys_key"),)

    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_accounts.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    route: Mapped[str] = mapped_column(String(200), nullable=False)
    # What was asked (sha256 of the route and the body): the same key with
    # another request is refused, not answered with the first one's result.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class ActivityEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "activity_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_activity_events_dedupe"),
        Index("ix_activity_events_kind_at", "kind", "at"),
        Index("ix_activity_events_workspace_at", "for_workspace_id", "at"),
        Index("ix_activity_events_user_at", "user_id", "at"),
    )

    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    for_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # The row it was read from (`intention:<id>`), so a figure can be traced.
    ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Correlation: the request it happened in, when its source kept one.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    properties: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)


class ActivityWatermark(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "activity_watermarks"
    __table_args__ = (UniqueConstraint("source", name="uq_activity_watermarks_source"),)

    source: Mapped[str] = mapped_column(String(40), nullable=False)
    read_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AdminCode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_codes"
    __table_args__ = (CheckConstraint(_among("purpose", CODE_PURPOSES), name="purpose"),)

    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(10), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AdminRolePermission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_role_permissions"
    __table_args__ = (
        UniqueConstraint("role", "permission", name="uq_admin_role_permissions_role_permission"),
        CheckConstraint(_among("role", ROLES), name="role"),
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    permission: Mapped[str] = mapped_column(String(40), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(320), nullable=False)
