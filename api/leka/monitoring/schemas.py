"""What the screens read of the watch (LEKA-442)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue


class MonitoringEntitlementRead(BaseModel):
    """What the workspace's plan includes of the watch — and, when it does
    not, the cheapest plan that does: never an alert simulated."""

    plan: str
    proactive: bool = Field(description="Its states are watched and alerts opened.")
    alerts: list[Literal["in_app", "email"]] = Field(description="How it is told.")
    contractual: bool
    provisional: bool = Field(description="Decided for the launch, to revisit.")
    alerts_from: str | None = Field(description="The cheapest plan that watches proactively.")
    email_from: str | None = Field(description="The cheapest plan that tells by e-mail.")


class AlertRead(BaseModel):
    """An alert: on what, what is wrong, how sure, from when to when, and
    what ended it."""

    id: uuid.UUID
    subject_type: Literal["entity", "source"]
    subject_id: uuid.UUID
    subject_name: str
    kind: Literal["unavailable", "degraded", "source_failing"]
    severity: Literal["high", "medium", "low"]
    certainty: Literal["confirmed", "suspected", "unverified"]
    status: Literal["open", "resolved", "closed"]
    opened_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    detail: dict[str, JsonValue]
    resolution: dict[str, JsonValue] | None = Field(
        description="The signal that verified it ended — or why it was closed without one."
    )
    notified: dict[str, JsonValue]
    acknowledged_at: datetime | None = Field(default=None, description="Taken in hand, when.")
    acknowledged_by: uuid.UUID | None = Field(default=None, description="By whom.")


class MonitoringRead(BaseModel):
    """The watch, as the screens show it: what the plan includes, what is
    open, what ended lately."""

    entitlement: MonitoringEntitlementRead
    open: list[AlertRead]
    ended: list[AlertRead] = Field(description="Resolved or closed in the last 7 days.")
