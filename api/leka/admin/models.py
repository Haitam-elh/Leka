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
session can ever stand in for it. Renewing it (LEKA-546) ends the row and
opens the next one of the same `family_id`, with a new token and the same
end: a device keeps one family from sign-in to its end, and an ended token
shown again ends the whole family. Why a row ended is `ended_reason`.

`admin_audit_events`: everything LEKA's team did and read through LEKA
ADMIN — signed in, refused, viewed what a customer wrote, suspended an
organisation, added credits. Append-only: the database refuses to change a
row, except to forget who it was about when an admin or an organisation is
deleted, and to delete one, except the nightly sweep's, past the retention
(LEKA-546). Kept apart from the customers' audit trail and its retention.

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

`admin_notes` (LEKA-549, LEKA-550): what LEKA's team writes down about an
organisation or a person, for each other, never shown to the customer: who,
when, what. Kept as written, never changed; deleted with what it is about.

`admin_daily_figures` (LEKA-548): what LEKA brings in each month, as it
stood each day (the MRR, its subscriptions, those whose price is not known),
written by the activity sweep, so that its evolution can be drawn: a price
is kept as it is now, never as it was.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.admin.access import AdminRole
from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

ROLES = tuple(role.value for role in AdminRole)
ACCOUNT_STATUSES = ("invited", "active", "disabled")
CODE_PURPOSES = ("invite", "reset")
# Incidents and the admins' notifications (LEKA-556): leka/admin/incidents.py.
INCIDENT_CATEGORIES = (
    "intention_failed",
    "agent_failed",
    "api_error",
    "integration_disconnected",
    "sync_failed",
    "credits",
    "payment_failed",
    "platform",
)
SEVERITIES = ("critical", "high", "medium", "low")
INCIDENT_STATUSES = ("new", "in_progress", "resolved", "closed")
# Being dealt with: what a same problem adds to, rather than opening another.
OPEN_STATUSES = ("new", "in_progress")
INCIDENT_EVENTS = (
    "opened",
    "occurred",
    "recurring",
    "assigned",
    "status",
    "note",
    "auto_resolved",
)
NOTIFICATION_KINDS = (
    "critical_incident",
    "payment_failed",
    "integration_disconnected",
    "repeated_errors",
    "capacity_near_limit",
    "abnormal_consumption",
)
# Why a session ended (LEKA-546): signed out on it; renewed into the next of
# its family; closed from another of the admin's devices; closed by a Super
# Admin; the password chosen or changed; the account disabled; an ended token
# shown again, which ends the family.
SESSION_END_REASONS = (
    "signed_out",
    "renewed",
    "ended_by_self",
    "ended_by_admin",
    "password",
    "disabled",
    "reused",
)
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
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_admin_sessions_token"),
        CheckConstraint(_among("ended_reason", SESSION_END_REASONS), name="ended_reason"),
        Index("ix_admin_sessions_family_id", "family_id"),
    )

    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # The first session of the device; its own id when it is the first.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    signed_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    # The admin's session it was done in (LEKA-546). No foreign key: ended
    # sessions are deleted after a while, the trail says which it was still.
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
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


class AdminNote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_notes"
    __table_args__ = (
        Index("ix_admin_notes_workspace_created", "for_workspace_id", "created_at"),
        Index("ix_admin_notes_user_created", "for_user_id", "created_at"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 4000", name="body"),
        # About an organisation or a person: one, never both, never none.
        CheckConstraint("num_nonnulls(for_workspace_id, for_user_id) = 1", name="about"),
    )

    for_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    for_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # Who wrote it: kept as an address too, so a note still says who once
    # that admin's account is gone.
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True
    )
    admin_email: Mapped[str] = mapped_column(String(320), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class AdminDailyFigure(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_daily_figures"
    __table_args__ = (UniqueConstraint("day", name="uq_admin_daily_figures_day"),)

    day: Mapped[date] = mapped_column(Date, nullable=False)
    # In euros, excluding VAT; null: no subscription's price is known.
    mrr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    # The paying subscriptions counted in it, and those whose price is not known.
    subscriptions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unknown: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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


class Incident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A problem LEKA's team must see (LEKA-556), opened by the incident watch
    from what LEKA CORE already records, never twice for the same problem
    while it is dealt with: `fingerprint` names it, unique among the open
    ones; a same problem adds an occurrence to it."""

    __tablename__ = "admin_incidents"
    __table_args__ = (
        CheckConstraint(_among("category", INCIDENT_CATEGORIES), name="category"),
        CheckConstraint(_among("severity", SEVERITIES), name="severity"),
        CheckConstraint(_among("status", INCIDENT_STATUSES), name="status"),
        CheckConstraint("occurrences >= 1", name="occurrences"),
        Index(
            "uq_admin_incidents_open_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=f"status IN {OPEN_STATUSES}",
        ),
        Index("ix_admin_incidents_status_seen", "status", "last_seen_at"),
        Index("ix_admin_incidents_workspace_seen", "for_workspace_id", "last_seen_at"),
    )

    # Said as INC-<number>.
    number: Mapped[int] = mapped_column(Integer, Identity(), nullable=False, unique=True)
    for_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="new")
    fingerprint: Mapped[str] = mapped_column(String(300), nullable=False)
    # What it is about, in LEKA CORE's own ids: an intention, an agent run, a
    # source, an invoice, a request, a rule.
    technical_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # What is said of it: names and codes, never a secret (scanned).
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Three times in a day: said, and its severity raised once.
    recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The same problem's incident before this one, resolved or closed.
    previous_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_incidents.id", ondelete="SET NULL"), nullable=True
    )


class IncidentEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An incident's history (LEKA-556), append-only: opened, each occurrence,
    recurring, assigned, its status changed, a note, resolved by LEKA when
    the problem went. `dedupe_key`: a same fact read twice is one event."""

    __tablename__ = "admin_incident_events"
    __table_args__ = (
        CheckConstraint(_among("kind", INCIDENT_EVENTS), name="kind"),
        UniqueConstraint("dedupe_key", name="uq_admin_incident_events_dedupe"),
        Index("ix_admin_incident_events_incident_at", "incident_id", "at"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_incidents.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Who at LEKA; none: LEKA itself, the incident watch.
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True
    )
    admin_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class AdminNotification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """What LEKA's team is told (LEKA-556): once each, its `dedupe_key`
    unique; read by each admin on their own."""

    __tablename__ = "admin_notifications"
    __table_args__ = (
        CheckConstraint(_among("kind", NOTIFICATION_KINDS), name="kind"),
        CheckConstraint(_among("severity", SEVERITIES), name="severity"),
        UniqueConstraint("dedupe_key", name="uq_admin_notifications_dedupe"),
        Index("ix_admin_notifications_at", "at"),
    )

    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    for_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_incidents.id", ondelete="SET NULL"), nullable=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class AdminNotificationRead(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_notification_reads"
    __table_args__ = (
        UniqueConstraint("notification_id", "admin_id", name="uq_admin_notification_reads"),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_notifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
