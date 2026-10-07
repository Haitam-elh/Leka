"""Types the intentions module exposes.

Approval is a value object, not a boolean. "Approved" without who and when
is not an approval — see docs/adr/004-agents-as-markdown.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from leka.context import AssembledContext
from leka.intentions.lifecycle import IntentionStatus

LinkKind = Literal["context", "finding", "entity", "decision", "action", "outcome"]
# What a person may link through the API: what exists today. Decisions,
# actions and outcomes are linked by what makes them (LEKA-390 to 392).
PersonLinkKind = Literal["context", "finding", "entity"]
Phase = Literal["active", "scheduled", "finished"]


class Approval(BaseModel):
    """Explicit, named, timestamped. All three, always."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    approved_at: datetime
    note: str | None = None


class ProposedAction(BaseModel):
    """What an agent suggests doing. Never what it did."""

    model_config = ConfigDict(frozen=True)

    intention_id: uuid.UUID
    summary: str
    rationale: str
    reversible: bool


class IntentionRead(BaseModel):
    """An intention, where it stands."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    title: str
    text: str
    kind: str | None = Field(description="What it asks for, as LEKA read it: diagnose, change…")
    scope: dict[str, JsonValue] = Field(description="The scope it was asked with.")
    status: IntentionStatus
    phase: Phase = Field(description="active, scheduled or finished: how a list groups it.")
    status_changed_at: datetime
    summary: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    context_id: uuid.UUID | None
    archived_at: datetime | None
    moves: list[IntentionStatus] = Field(description="The states it may go to next.")


class IntentionLinkRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    kind: LinkKind
    ref_id: uuid.UUID
    label: str
    detail: dict[str, JsonValue]
    linked_at: datetime
    linked_by: uuid.UUID | None


class IntentionEventRead(BaseModel):
    """One thing that happened to it, as its history keeps it."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    sequence: int
    kind: Literal["created", "moved", "linked", "unlinked", "archived", "restored"]
    name: str | None = Field(description="A move's name: proposed, approved, failed…")
    from_status: IntentionStatus | None
    to_status: IntentionStatus | None
    actor: Literal["person", "system"]
    by: uuid.UUID | None
    at: datetime
    reason: str | None
    detail: dict[str, JsonValue]


class IntentionDetail(IntentionRead):
    """An intention with what it is linked to."""

    links: list[IntentionLinkRead]


class IntentionCreated(BaseModel):
    """An intention kept, and the context assembled for it (LEKA-373)."""

    intention: IntentionDetail
    context: AssembledContext


class IntentionAsked(BaseModel):
    """An intention asked again: as it now stands, its context's new version."""

    intention: IntentionDetail
    context: AssembledContext


class Withdrawal(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class IntentionLinkCreate(BaseModel):
    kind: PersonLinkKind
    ref_id: uuid.UUID


class IntentionCounts(BaseModel):
    """How many, by phase — and archived — for a list's tabs (mockup 07)."""

    all: int
    active: int
    scheduled: int
    finished: int
    archived: int
