"""What the screens read of the watch (LEKA-442)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class MonitoringEntitlementRead(BaseModel):
    """What the workspace's plan includes of the watch — and, when it does
    not, the cheapest plan that does: never an alert simulated."""

    plan: str
    proactive: bool = Field(description="Its states are watched and alerts opened.")
    alerts: list[Literal["in_app", "email", "slack", "teams", "discord"]] = Field(
        description="How it is told."
    )
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


# ── the rules a person sets (LEKA-477) ──────────────────────────────────────

Condition = Literal["unavailable", "degraded", "source_failing"]
ChannelKey = Literal["in_app", "email", "sms", "whatsapp", "slack", "teams", "discord"]
Severity = Literal["high", "medium", "low"]


class WatchableRead(BaseModel):
    """What a rule may be set on: its state read by a source, and when."""

    subject_type: Literal["entity", "source"]
    subject_id: uuid.UUID
    name: str
    kind: str = Field(description="service, database, infra_resource, source.")
    conditions: list[Condition] = Field(description="The troubles LEKA can see on it.")
    state: str
    fresh: bool
    observed_at: datetime | None


class ChannelRead(BaseModel):
    """A way to tell, and where it stands here: operational only once a
    delivery went — never said so before."""

    key: ChannelKey
    status: Literal[
        "operational", "untested", "failing", "not_connected", "not_in_plan", "unavailable"
    ]
    hint: str | None = Field(
        default=None, description="A webhook's (LEKA-496): its host and last characters only."
    )
    error: str | None = Field(
        default=None, description="Its last delivery's error, when it failed."
    )


class WebhookConnect(BaseModel):
    """A channel's webhook, as its tool gives it (LEKA-496)."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=10, max_length=600)


class AlertDeliveryRead(BaseModel):
    """One telling: sent, or failed and why."""

    id: uuid.UUID
    alert_id: uuid.UUID | None = Field(description="None: a test.")
    channel: ChannelKey
    recipient: str
    round: int
    status: Literal["sent", "failed"]
    error: str | None
    at: datetime


class AlertRuleRead(BaseModel):
    id: uuid.UUID
    name: str
    subject_type: Literal["entity", "source"]
    subject_id: uuid.UUID
    subject_name: str
    conditions: list[Condition]
    severity: Severity
    confirm_minutes: int
    repeat_hours: int | None
    channels: list[ChannelKey]
    recipients: list[uuid.UUID]
    enabled: bool
    created_at: datetime
    deliveries: list[AlertDeliveryRead] = Field(
        default_factory=list, description="Its latest tellings, the latest first."
    )


class AlertRulesRead(BaseModel):
    """The rules, and all a screen needs to set one: what may be watched,
    the channels, the plan's limit and how many are on."""

    limit: int | None = Field(description="The plan's alert rules; None: no limit.")
    used: int = Field(description="Those on now.")
    upgrade: str | None = Field(description="The cheapest plan that allows more, at the limit.")
    channels: list[ChannelRead]
    watchable: list[WatchableRead]
    rules: list[AlertRuleRead]


class AlertRuleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    subject_type: Literal["entity", "source"]
    subject_id: uuid.UUID
    conditions: list[Condition] = Field(min_length=1, max_length=3)
    severity: Severity = "medium"
    confirm_minutes: int = Field(default=0, ge=0, le=1440)
    repeat_hours: int | None = Field(default=None, ge=1, le=168)
    channels: list[ChannelKey] = Field(min_length=1, max_length=7)
    recipients: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    enabled: bool = True


class AlertRuleChange(BaseModel):
    """Any of it; what is left out stays as it was."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    conditions: list[Condition] | None = Field(default=None, min_length=1, max_length=3)
    severity: Severity | None = None
    confirm_minutes: int | None = Field(default=None, ge=0, le=1440)
    repeat_hours: int | None = Field(default=None, ge=1, le=168)
    channels: list[ChannelKey] | None = Field(default=None, min_length=1, max_length=7)
    recipients: list[uuid.UUID] | None = Field(default=None, max_length=50)
    enabled: bool | None = None


class NightPointRead(BaseModel):
    """One thing the night review found to look at."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["alert", "source", "findings", "decisions", "conflicts", "change", "runs"]
    severity: Literal["high", "medium", "low"]
    name: str = ""
    count: int = 1
    href: str
    ask: bool = False
    params: dict[str, JsonValue] = Field(default_factory=dict)


class NightReviewRead(BaseModel):
    """What LEKA went through overnight, and what it found."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    at: datetime
    trigger: Literal["night", "asked"]
    checked: dict[str, int]
    points: list[NightPointRead]


class WorkingRead(BaseModel):
    """One piece of work under way (monitoring/now.py)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["intention", "agent", "source", "repair"]
    title: str
    step: str
    since: datetime | None = None
    href: str
