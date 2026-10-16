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

from sqlalchemy import CheckConstraint, DateTime, Index, String, text
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
