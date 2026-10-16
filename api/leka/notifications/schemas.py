"""The notification centre's contract (LEKA-476)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Category = Literal["intention", "source", "monitoring", "billing", "agent", "workspace"]
Severity = Literal["info", "success", "warning", "critical"]


class NotificationOut(BaseModel):
    """One notification, as its reader sees it: what happened (its kind and
    what its words are made of — said in the reader's language by the
    screen), how grave, when, where it leads, and whether they read it."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    category: Category
    kind: str = Field(description="intention.decision_required, alert.triggered, billing.renewed…")
    severity: Severity
    params: dict[str, JsonValue] = Field(description="Its words' parts: a title, a name, a plan…")
    link: str | None = Field(description="Where it leads, a path of the application.")
    occurred_at: datetime
    read: bool


class NotificationPage(BaseModel):
    data: list[NotificationOut]
    next_cursor: str | None = Field(description="The next page's, none at the last.")
    unread: int = Field(description="How many of theirs are unread, the muted left out.")


class UnreadCount(BaseModel):
    unread: int


class MarkAll(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category | None = None


class Marked(BaseModel):
    marked: int


class NotificationPreferences(BaseModel):
    """What a person does not want told in the centre — in the application
    only: the monitoring alerts' e-mails are set with the alerts."""

    model_config = ConfigDict(extra="forbid")

    muted: list[Category] = Field(default_factory=list, max_length=6)
