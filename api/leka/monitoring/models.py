"""An alert on the environment (LEKA-442): a thing, or a source, found
unavailable, degraded or failing — kept from when it opened to when a
signal verified it ended.

One open alert per thing and per kind of trouble: the same trouble seen
again moves its last sighting, never opens another (a partial unique
index). Its certainty follows the data — confirmed by a record, suspected
from a deduction, unverified while what it rests on is stale. It is
resolved only by a fresh signal that says the thing is well; silence
resolves nothing. A thing gone from the model closes it, said why.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin

SUBJECTS = ("entity", "source")
KINDS = ("unavailable", "degraded", "source_failing")
SEVERITIES = ("high", "medium", "low")
CERTAINTIES = ("confirmed", "suspected", "unverified")
STATUSES = ("open", "resolved", "closed")


def _among(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class MonitoringAlert(Base, WorkspaceScopedMixin):
    __tablename__ = "monitoring_alerts"
    __table_args__ = (
        CheckConstraint(_among("subject_type", SUBJECTS), name="subject_type"),
        CheckConstraint(_among("kind", KINDS), name="kind"),
        CheckConstraint(_among("severity", SEVERITIES), name="severity"),
        CheckConstraint(_among("certainty", CERTAINTIES), name="certainty"),
        CheckConstraint(_among("status", STATUSES), name="status"),
        # One open alert per thing and kind of trouble: deduplicated.
        Index(
            "uq_monitoring_alerts_open",
            "workspace_id",
            "subject_id",
            "family",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_monitoring_alerts_workspace_status", "workspace_id", "status", "opened_at"),
    )

    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # The resolved entity, or the source.
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(300), nullable=False)
    # The trouble's family — health or source — so that degraded turning
    # unavailable is the same alert, made worse, not a second one.
    family: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    certainty: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Why it opened: the state's reason, the incident it rests on, the
    # sources that said it.
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # What ended it: the signal that verified it, from where, when — or why
    # it was closed without one.
    resolution: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # Who was told, how, when: {"email": "<iso>"}.
    notified: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Seen and taken in hand (LEKA-463): by whom, when — the first only. An
    # acknowledged alert stays open until a signal says the trouble ended.
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


# ── the rules a person sets (LEKA-477) ──────────────────────────────────────

# Every way LEKA may one day tell; only those integrated are ever offered.
CHANNELS = ("in_app", "email", "sms", "whatsapp", "slack", "teams", "discord")
# Told through the webhook a person connects (LEKA-496).
WEBHOOK_CHANNELS = ("slack", "teams", "discord")
DELIVERIES = ("sent", "failed")


class AlertRule(Base, WorkspaceScopedMixin):
    """« Tell me when this goes wrong »: on one thing or source the watch
    reads, for the troubles it can see there, how bad, after how long, how
    often, to whom and how. Told once per episode (an alert), again only
    as often as asked while it stays open and nobody took it in hand."""

    __tablename__ = "monitoring_alert_rules"
    __table_args__ = (
        CheckConstraint(_among("subject_type", SUBJECTS), name="subject_type"),
        CheckConstraint(_among("severity", SEVERITIES), name="severity"),
        CheckConstraint("confirm_minutes >= 0", name="confirm_minutes"),
        CheckConstraint("repeat_hours IS NULL OR repeat_hours > 0", name="repeat_hours"),
        Index("ix_monitoring_alert_rules_workspace_enabled", "workspace_id", "enabled"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(300), nullable=False)
    # The troubles it is about: unavailable, degraded, source_failing.
    conditions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    # Open this long before anyone is told: no fleeting alert.
    confirm_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Told again every so many hours while open and not taken in hand; none:
    # once per episode.
    repeat_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # Members' ids, told by e-mail.
    recipients: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class AlertDelivery(Base, WorkspaceScopedMixin):
    """One telling, kept: which rule, which alert (none: a test), how, to
    whom, whether it went — a failure said, never hidden. Once per rule,
    alert, channel, recipient and round: never told twice."""

    __tablename__ = "monitoring_alert_deliveries"
    __table_args__ = (
        CheckConstraint(_among("channel", CHANNELS), name="channel"),
        CheckConstraint(_among("status", DELIVERIES), name="status"),
        Index(
            "uq_monitoring_alert_deliveries_once",
            "rule_id",
            "alert_id",
            "channel",
            "recipient",
            "round",
            unique=True,
            postgresql_where=text("alert_id IS NOT NULL"),
        ),
        Index("ix_monitoring_alert_deliveries_rule_at", "rule_id", "at"),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monitoring_alert_rules.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monitoring_alerts.id", ondelete="CASCADE"),
        nullable=True,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelEndpoint(Base, WorkspaceScopedMixin):
    """A channel connected by a webhook (LEKA-496): Slack, Microsoft Teams,
    Discord — one each a workspace, its URL encrypted (SecretBox), never
    read back whole: what is shown is its hint. Where it stands: untested
    until a message went, then operational or failing, its last error said."""

    __tablename__ = "monitoring_channel_endpoints"
    __table_args__ = (
        UniqueConstraint("workspace_id", "channel", name="uq_monitoring_channel_endpoints_channel"),
        CheckConstraint("channel IN ('slack', 'teams', 'discord')", name="channel"),
        CheckConstraint("status IN ('untested', 'operational', 'failing')", name="status"),
    )

    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    webhook_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Its host and last characters: enough to recognise it, never to use it.
    hint: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="untested")
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class NightReview(Base, WorkspaceScopedMixin):
    """What LEKA went through overnight, and what it found to look at
    (2026-10-29, after Polsia's « travaille pendant que vous dormez »):
    each review kept — when, how many of each thing it read (`checked`),
    and its points, the most serious first, each with where to see it and
    what to ask of LEKA about it (monitoring/night.py)."""

    __tablename__ = "night_reviews"
    __table_args__ = (
        CheckConstraint("trigger IN ('night', 'asked')", name="trigger"),
        Index("ix_night_reviews_workspace_at", "workspace_id", "at"),
    )

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)
    checked: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    points: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    asked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
