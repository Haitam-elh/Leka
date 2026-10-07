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
    # LEKA-386: what defines how it must be processed, missing or at odds.
    "missing_environment",
    "missing_target",
    "conflicting_constraints",
    "subject_gone",
    "subject_dormant",
    "everything_excluded",
]
ConstraintKind = Literal[
    "exclude",
    "read_only",
    "no_downtime",
    "deadline",
    "window",
    "urgency",
    "environment_only",
    "target",
    "services",
    "sources",
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


class ScopedEntity(BaseModel):
    """A thing of the company model the intention is about — or excludes —
    as the model knows it now (LEKA-386)."""

    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID
    name: str
    type: str
    how: Literal["asked", "named", "business"]
    said: str | None
    confidence: float
    lifecycle: str | None = Field(description="active, dormant, archived, removed; none: unread.")


class ScopeConstraint(BaseModel):
    """A boundary the analysis — and anything done — must keep to."""

    model_config = ConfigDict(frozen=True)

    kind: ConstraintKind
    said: str = Field(description="The words that say it; « asked » when the form did.")
    value: JsonValue = None
    hard: bool = Field(description="Must hold — else it only weighs.")


class ScopePeriod(BaseModel):
    """When it looks — and whether the asker said so."""

    model_config = ConfigDict(frozen=True)

    since: datetime
    until: datetime
    origin: Literal["asked", "text", "kind", "model"]
    said: str | None
    explicit: bool = Field(description="Asked, or read from its words — not its kind's default.")


class IntentScope(BaseModel):
    """What the intention is about and within which boundaries it must be
    processed (LEKA-386): its things, resolved against the company model,
    and those it excludes; where; when; under what constraints; what
    critical information is missing. docs/intentions.md § 10."""

    model_config = ConfigDict(frozen=True)

    entities: list[ScopedEntity]
    excluded: list[ScopedEntity]
    environments: list[str] = Field(description="Where it is held to; none: everywhere.")
    environment_origin: Literal["asked", "text", "constraint"] | None
    period: ScopePeriod | None
    sources: list[uuid.UUID] = Field(description="The sources it is held to; none: every one.")
    constraints: list[ScopeConstraint]
    missing: list[str] = Field(description="The critical information missing: ambiguity kinds.")


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
    scope: IntentScope | None = Field(
        default=None, description="Its scope and constraints (LEKA-386, version 2 on)."
    )


class ReadinessIssue(BaseModel):
    """A gap or a conflict of an intention's context, surfaced before its
    analysis (LEKA-387)."""

    model_config = ConfigDict(frozen=True)

    origin: Literal["gap", "conflict"]
    kind: str
    severity: Literal["critical", "warning", "info"]
    said: str
    refs: list[uuid.UUID] = Field(default_factory=list)
    gap_origin: Literal["quality", "intent"] | None = Field(
        default=None, description="A gap's: the context's quality (LEKA-375), or the reading."
    )
    detail: dict[str, JsonValue] = Field(default_factory=dict)
    label: str | None = Field(default=None, description="A conflict's: what it is about.")
    about: str | None = Field(default=None, description="A conflict's: the attribute or role.")


class ContextReadiness(BaseModel):
    """Whether an intention's context can ground its analysis (LEKA-387):
    `ready`; `limited` — it holds something, warnings said; `blocked` — a
    critical gap or conflict first. Read from the context's own quality
    (LEKA-375) and conflicts (LEKA-372), never judged again."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "limited", "blocked"]
    context_id: uuid.UUID
    version: int
    level: str = Field(description="The context's quality level: high, medium, low.")
    score: float | None
    elements: int
    facets: dict[str, int] = Field(
        description="The things it holds by side: technical, business, organizational, temporal."
    )
    sources: int = Field(description="The sources its elements came from.")
    critical: list[ReadinessIssue]
    warnings: list[ReadinessIssue]


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
    readiness: ContextReadiness | None = Field(
        default=None, description="Whether its context can ground its analysis (LEKA-387)."
    )


class IntentionCreated(BaseModel):
    """An intention kept, and the context assembled for it (LEKA-373)."""

    intention: IntentionDetail
    context: AssembledContext


class IntentionContext(BaseModel):
    """An intention's context, as downstream capabilities read it (LEKA-387):
    the context engine's contract (LEKA-376), and whether it can ground an
    analysis."""

    context: AssembledContext
    readiness: ContextReadiness


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
