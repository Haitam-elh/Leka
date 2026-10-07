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

Goal = Literal[
    "explain_cause",
    "find_change",
    "find_owner",
    "map_dependencies",
    "assess_impact",
    "check_compliance",
    "plan_migration",
    "find_knowledge",
    "investigate",
    "act",
    "unknown",
]
Mode = Literal["question", "request"]
AmbiguityKind = Literal[
    "too_short",
    "unclear_goal",
    "competing_goals",
    "no_subject",
    "unknown_subject",
    "ambiguous_subject",
    "action_without_target",
    "several_requests",
    "unknown_environment",
]
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


class GoalRead(BaseModel):
    """What the asker wants to achieve, as LEKA understood it (LEKA-385)."""

    model_config = ConfigDict(frozen=True)

    code: Goal
    said: list[str] = Field(description="The words that say it, as written (folded).")
    confidence: float = Field(description="0 to 1: 0 when it could not be told.")


class ActionRead(BaseModel):
    """Something the asker wants done, or done to something."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(
        description="restart, rollback, deploy, scale, stop, fix, update, migrate, "
        "investigate, compare, assess, list, document, notify, ticket."
    )
    said: str = Field(description="The word that says it.")
    changes_systems: bool = Field(
        description="It would change a customer's systems: only after a person approves "
        "(LEKA-390, 391)."
    )


class UnderstoodEntity(BaseModel):
    """A thing the intention is about, and how LEKA knows."""

    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID
    name: str
    type: str
    how: Literal["asked", "named", "business"]
    said: str | None
    confidence: float


class AmbiguityRead(BaseModel):
    """What LEKA cannot tell, and what it would ask to tell it."""

    model_config = ConfigDict(frozen=True)

    kind: AmbiguityKind
    blocking: bool = Field(description="It cannot go on without an answer.")
    said: str = Field(description="What is ambiguous, in English.")
    options: list[str] = Field(
        default_factory=list, description="What it could mean: things, goals."
    )


class Understanding(BaseModel):
    """What LEKA understood of an intention (LEKA-385): the structured
    intent, every part of it with the words it came from — the original
    wording kept beside it. docs/intentions.md § 9."""

    model_config = ConfigDict(frozen=True)

    version: int
    text: str = Field(description="The words, as asked.")
    mode: Mode = Field(description="A question to answer, or a request to act on.")
    mode_said: str | None = Field(description="What said it: « ? », « pourquoi », « redémarre ».")
    kind: str = Field(description="What it asks the company model for (LEKA-373).")
    goal: GoalRead
    actions: list[ActionRead]
    entities: list[UnderstoodEntity]
    period: dict[str, JsonValue] | None = Field(description="since, until, origin, said.")
    environment: str | None
    ambiguities: list[AmbiguityRead]
    clear: bool = Field(description="No blocking ambiguity: it can be analysed.")


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
    goal: Goal | None = Field(description="What it wants to achieve, as understood (LEKA-385).")


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
    """An intention with what it is linked to, and what LEKA understood."""

    links: list[IntentionLinkRead]
    understanding: Understanding | None


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
