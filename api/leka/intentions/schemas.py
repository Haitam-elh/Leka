"""Types the intentions module exposes.

Approval is a value object, not a boolean. "Approved" without who and when
is not an approval — see docs/adr/004-agents-as-markdown.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue

from leka.connectors import PublicHttpsUrl
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


# ── its analysis (LEKA-388) ──────────────────────────────────────────────────


class AnalysisNote(BaseModel):
    """A sentence the interface words: its code and values — and in
    English."""

    model_config = ConfigDict(frozen=True)

    code: str
    text: str
    params: dict[str, JsonValue] = Field(default_factory=dict)


class EvidenceSourceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID | None
    kind: str | None
    name: str | None = Field(description="None when the source has been deleted since.")


class AnalysisEvidence(BaseModel):
    """One thing a statement rests on, and where it came from."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Stable: entity:<id>, tie:<from>:<type>:<to>, event:<id>…")
    kind: Literal["record", "entity", "event", "inference"]
    label: str
    ref_type: str | None = Field(description="Its kind — service, deployment — or the tie's.")
    ref_id: uuid.UUID | None = Field(description="What it is in the company model, or a finding.")
    sources: list[EvidenceSourceRead] = Field(description="Where it was read.")
    records: list[str] = Field(description="The records that stated it.")
    origin: str | None = Field(description="stated, inferred, accepted — or leka.")
    confidence: float | None
    detail: str | None
    at: datetime | None
    params: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="What its label is made of: a tie's from and to; a finding's code and params.",
    )


class AnalysisStatement(BaseModel):
    """A fact: what a source says, or LEKA observed."""

    model_config = ConfigDict(frozen=True)

    id: str
    capability: str
    code: str
    text: str
    params: dict[str, JsonValue]
    evidence: list[str] = Field(description="The ids of its evidence.")


class AnalysisCause(BaseModel):
    """A hypothesis: what may explain it, and how sure."""

    model_config = ConfigDict(frozen=True)

    id: str
    capability: str
    code: str
    label: str
    basis: Literal["stated", "inferred"]
    why: str
    confidence: float | None
    ref_type: str | None
    ref_id: uuid.UUID | None
    params: dict[str, JsonValue]
    evidence: list[str]


class AnalysisImpactItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref_type: str
    ref_id: uuid.UUID
    name: str


class AnalysisImpactArea(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: Literal["dependents", "applications", "capabilities", "processes"]
    items: list[AnalysisImpactItem]


class IntentionAnalysisResult(BaseModel):
    """What the analysis came to, for the decision interface (LEKA-389)."""

    model_config = ConfigDict(frozen=True)

    status: Literal["complete", "partial", "inconclusive", "failed"]
    summary: list[AnalysisNote]
    findings: list[AnalysisStatement]
    causes: list[AnalysisCause]
    impact: list[AnalysisImpactArea]
    risk: Literal["high", "medium", "low", "unknown"]
    risk_basis: AnalysisNote | None
    uncertainties: list[AnalysisNote]
    missing: list[AnalysisNote]
    confidence: float | None
    support: list[AnalysisNote]
    evidence: list[AnalysisEvidence]


class CapabilityChoiceRead(BaseModel):
    """A capability considered, and why it ran or not."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    method: Literal["rules", "model"]
    chosen: bool
    reason: str = Field(
        description="always, goal, kind, acting — or no_model (it waits for LEKA-394), not_called."
    )


class AnalysisStepRead(BaseModel):
    """What one capability did."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    status: Literal["succeeded", "failed", "timed_out", "skipped"]
    duration_ms: int
    error: str | None
    reason: str | None


class IntentionAnalysisRead(BaseModel):
    """One analysis of an intention: how it went, and what it came to."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    intention_id: uuid.UUID
    number: int
    trigger: Literal["created", "asked_again", "requested", "sweep"]
    status: Literal["running", "complete", "partial", "inconclusive", "failed", "blocked"]
    requested_by: uuid.UUID | None
    context_id: uuid.UUID | None
    context_version: int | None
    readiness: Literal["ready", "limited", "blocked"] | None
    started_at: datetime
    finished_at: datetime | None
    selection: list[CapabilityChoiceRead]
    steps: list[AnalysisStepRead]
    result: IntentionAnalysisResult | None
    error: str | None
    detail: dict[str, JsonValue]


class IntentionAnalysisRequested(BaseModel):
    """An analysis asked for: queued, or one already on its way."""

    model_config = ConfigDict(frozen=True)

    queued: bool


# ── decisions (LEKA-390) ──────────────────────────────────────────────────────


class ProposalTargetRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    type: str


class ProposalRead(BaseModel):
    """One action proposed: what, on what, where, within which constraints,
    whether it can be undone."""

    model_config = ConfigDict(frozen=True)

    id: str
    action: str
    targets: list[ProposalTargetRead]
    environment: str | None
    constraints: list[dict[str, JsonValue]]
    reversible: bool | None


class DecisionVoteRead(BaseModel):
    """A vote, as kept: who, when, why, on which revision, in which context."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    revision: int
    verdict: Literal["approve", "reject", "modify", "request_changes"]
    by: uuid.UUID | None = Field(description="None once the user is deleted.")
    at: datetime
    reason: str | None
    changes: dict[str, JsonValue]
    context: dict[str, JsonValue]


class DecisionRead(BaseModel):
    """A decision on what an intention asks to do: where it stands, what it
    needs, what was voted."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    intention_id: uuid.UUID
    number: int
    status: Literal["proposed", "approved", "rejected", "changes_requested", "superseded"]
    open: bool = Field(description="Proposed, and its intention awaiting a decision: votable.")
    risk: Literal["low", "medium", "high"]
    analysis_risk: str | None
    revision: int
    required_approvals: int
    separate_asker: bool = Field(description="The asker may not be one of the approvers.")
    approvers: list[uuid.UUID] = Field(description="Who approved its current revision, in order.")
    proposals: list[ProposalRead]
    analysis_id: uuid.UUID | None
    context_version: int | None
    asked_by: uuid.UUID | None
    created_at: datetime
    decided_at: datetime | None
    votes: list[DecisionVoteRead]


class DecisionIntention(BaseModel):
    """The intention a decision is on, as the queue shows it."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    title: str
    status: str
    kind: str | None
    created_by: uuid.UUID | None
    summary: str | None


class DecisionQueueItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: DecisionRead
    intention: DecisionIntention


class DecisionQueuePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[DecisionQueueItem]


class DecisionSummary(BaseModel):
    """How many decisions stand where — for À valider's figures."""

    model_config = ConfigDict(frozen=True)

    proposed: int
    approved: int
    rejected: int
    changes_requested: int
    superseded: int


class ApprovalPolicyRead(BaseModel):
    """How many must approve, per risk; when the asker may not be one."""

    model_config = ConfigDict(frozen=True)

    approvals: dict[Literal["low", "medium", "high"], int]
    separate: list[Literal["low", "medium", "high"]]
    production_raises: bool
    customised: bool = Field(description="False: LEKA's default policy.")


class ApprovalPolicyUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approvals: dict[Literal["low", "medium", "high"], int] = Field(default_factory=dict)
    separate: list[Literal["low", "medium", "high"]] | None = None
    production_raises: bool | None = None


class DecisionVoteRequest(BaseModel):
    """A vote: why — required to reject, modify or ask for changes — and,
    to modify, where it should run and which actions are kept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)
    environment: str | None = Field(default=None, min_length=1, max_length=60)
    keep: list[str] | None = Field(default=None, max_length=20)


# ── execution (LEKA-391) ──────────────────────────────────────────────────────


class ActionEndpointRead(BaseModel):
    """A system the workspace authorized LEKA to act through — never its
    secret."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    actions: list[str]
    environments: list[str]
    targets: list[uuid.UUID]
    enabled: bool
    created_by: uuid.UUID | None
    created_at: datetime
    last_called_at: datetime | None


class ActionEndpointCreated(BaseModel):
    """Made: its signing secret, shown this once."""

    model_config = ConfigDict(frozen=True)

    endpoint: ActionEndpointRead
    secret: str = Field(description="Verifies X-Leka-Signature. Shown once; kept encrypted.")


class ActionEndpointCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    url: PublicHttpsUrl
    actions: list[str] = Field(min_length=1, max_length=30)
    environments: list[str] = Field(min_length=1, max_length=20)
    targets: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class ActionEndpointUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    actions: list[str] | None = Field(default=None, min_length=1, max_length=30)
    environments: list[str] | None = Field(default=None, min_length=1, max_length=20)
    targets: list[uuid.UUID] | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class PlanCheckRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    passed: bool
    detail: dict[str, JsonValue]


class IntentionPlanStepRead(BaseModel):
    """One action of a plan, how it went, and its evidence."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    position: int
    proposal_id: str
    action: str
    targets: list[dict[str, JsonValue]]
    environment: str | None
    constraints: list[dict[str, JsonValue]]
    executor: Literal["webhook", "manual"]
    endpoint_id: uuid.UUID | None
    endpoint_name: str | None
    status: Literal["pending", "running", "awaiting", "succeeded", "failed", "cancelled", "skipped"]
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    evidence: dict[str, JsonValue]


class IntentionPlanEventRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    step_id: uuid.UUID | None
    kind: str
    actor: Literal["person", "system"]
    by: uuid.UUID | None
    at: datetime
    detail: dict[str, JsonValue]


class IntentionPlanRead(BaseModel):
    """What an approved decision became, and how it is going."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    intention_id: uuid.UUID
    decision_id: uuid.UUID
    number: int
    revision: int
    status: Literal[
        "planned", "scheduled", "running", "succeeded", "failed", "cancelled", "blocked"
    ]
    created_by: uuid.UUID | None
    started_by: uuid.UUID | None
    timezone: str
    scheduled_for: datetime | None
    suggested_for: datetime | None = Field(
        description="When its window next opens, when it was asked in one."
    )
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    checks: list[PlanCheckRead]
    error: str | None
    steps: list[IntentionPlanStepRead]
    events: list[IntentionPlanEventRead]


class PlanStartRequest(BaseModel):
    """Run now — or at a moment, when given."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scheduled_for: datetime | None = None
    timezone: str = Field(default="UTC", max_length=64)


class PlanCancelRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class StepReportRequest(BaseModel):
    """A person says how a step went: done, or failed — and what shows it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["succeeded", "failed"]
    note: str = Field(min_length=1, max_length=2000)
    link: HttpUrl | None = Field(default=None, description="http or https only.")
