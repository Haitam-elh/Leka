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


class UnderstoodBy(BaseModel):
    """Who read it (LEKA-394): LEKA's rules, or a language model with them."""

    model_config = ConfigDict(frozen=True)

    method: Literal["rules", "model"]
    provider: str | None = None
    model: str | None = None
    version: str | None = None
    confidence: float | None = Field(default=None, description="The model's, of its goal.")
    run_id: uuid.UUID | None = Field(
        default=None,
        description="The LLM runtime's run that read it (LEKA-430): what reading it cost —"
        " a model asked, even when the rules' reading was kept.",
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
    scope: IntentScope | None = Field(
        default=None, description="Its scope and constraints (LEKA-386, version 2 on)."
    )
    restated: str | None = Field(
        default=None, description="What is asked, in a sentence, as a model read it (LEKA-394)."
    )
    read_by: UnderstoodBy | None = Field(
        default=None, description="Who read it; none: LEKA's rules, before LEKA-394."
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


class AnalysisPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    cites: list[str] = Field(description="The findings, causes and evidence it rests on (ids).")


class AnalysisAnswer(BaseModel):
    """The analysis answered in words by a language model (LEKA-394): only
    what the analysis holds, each point citing what it rests on."""

    model_config = ConfigDict(frozen=True)

    text: str
    points: list[AnalysisPoint]
    caveats: list[str]
    provider: str
    model: str
    version: str


class RecommendationTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref_type: str
    ref_id: uuid.UUID
    name: str


class AnalysisRecommendation(BaseModel):
    """What LEKA proposes to do (LEKA-389) — a proposal, never a fact: from
    the findings and causes it names (`basis`), on the evidence they rest
    on; a person decides."""

    model_config = ConfigDict(frozen=True)

    id: str
    code: str = Field(
        description="recommend.rollback, recommend.assign_owner… — worded by the interface."
    )
    text: str = Field(description="In English, for what reads it without a dictionary.")
    params: dict[str, JsonValue]
    action: Literal["rollback", "change", "monitor", "other"]
    changes_systems: bool = Field(
        description="It would change a customer's systems: only once a person approves (LEKA-390)."
    )
    priority: Literal["high", "medium", "low"]
    risk: Literal["high", "medium", "low", "unknown"]
    reversible: bool | None
    confidence: float | None = Field(
        description="Never surer than what it follows from; none when it is not a bet."
    )
    why: AnalysisNote
    basis: list[str] = Field(description="The ids of the findings and causes it follows from.")
    evidence: list[str] = Field(description="The ids of the evidence they rest on.")
    target: RecommendationTarget | None


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
    answer: AnalysisAnswer | None = Field(
        default=None, description="Written by a model from the above, when one can (LEKA-394)."
    )
    recommendations: list[AnalysisRecommendation] = Field(
        default_factory=list,
        description="What LEKA proposes, apart from what it found (LEKA-389).",
    )


class CapabilityChoiceRead(BaseModel):
    """A capability considered, and why it ran or not."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    method: Literal["rules", "model"]
    chosen: bool
    reason: str = Field(
        description="always, goal, kind, acting — or no_model (no model can run it here), "
        "disabled (turned off in the workspace's catalogue, LEKA-393), not_called."
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
    # Where it ran in the plan (LEKA-399). An analysis kept before has none.
    level: int = Field(default=0, description="Its level: each after the one before.")
    started_ms: int = Field(default=0, description="When it started, after the analysis did.")
    handed: list[str] = Field(
        default_factory=list, description="The capabilities whose output it was handed."
    )
    degraded: list[str] = Field(
        default_factory=list, description="What it reads that did not succeed: run without."
    )
    fallback_of: str | None = Field(default=None, description="The one it ran in place of.")


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
    on_behalf_of: uuid.UUID | None = Field(
        default=None, description="Cast with this person's authority, delegated (LEKA-404)."
    )
    role: str | None = Field(default=None, description="The role of the authority used.")


class DecisionGovernanceRead(BaseModel):
    """What the policy said of a decision (LEKA-404): why its risk, what it
    needs, what froze or waived it, when it is escalated."""

    model_config = ConfigDict(frozen=True)

    reasons: list[dict[str, JsonValue]] = Field(default_factory=list)
    required_role: str | None = None
    valid_hours: int | None = None
    escalate_at: datetime | None = None
    escalated_at: datetime | None = None
    valid_until: datetime | None = None
    frozen: bool = False
    waived: bool = False
    exceptions: list[dict[str, JsonValue]] = Field(default_factory=list)


class DecisionRead(BaseModel):
    """A decision on what an intention asks to do: where it stands, what it
    needs, what was voted."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    intention_id: uuid.UUID
    number: int
    status: Literal["proposed", "approved", "rejected", "changes_requested", "superseded"]
    open: bool = Field(description="Proposed, and its intention awaiting a decision: votable.")
    risk: Literal["low", "medium", "high", "critical"]
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
    governance: DecisionGovernanceRead = Field(default_factory=DecisionGovernanceRead)


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


class RiskRuleRead(BaseModel):
    """A rule that raises a decision's risk (LEKA-404): when every condition
    it says holds of one proposed action — a list left empty holds of any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    at_least: Literal["low", "medium", "high", "critical"]
    actions: list[str] = Field(default_factory=list, max_length=30)
    environments: list[str] = Field(default_factory=list, max_length=30)
    target_types: list[str] = Field(default_factory=list, max_length=30)
    target_criticality: list[str] = Field(default_factory=list, max_length=30)
    reversible: bool | None = None


Level = Literal["low", "medium", "high", "critical"]


class ApprovalPolicyRead(BaseModel):
    """The workspace's governance of consequential actions: how risk is
    classified, and per risk who must approve, how long an approval holds,
    when a decision waiting is escalated."""

    model_config = ConfigDict(frozen=True)

    approvals: dict[Level, int]
    separate: list[Level]
    production_raises: bool
    roles: dict[Level, Literal["admin", "owner"] | None]
    valid_hours: dict[Level, int | None]
    escalate_hours: dict[Level, int | None]
    rules: list[RiskRuleRead]
    customised: bool = Field(description="False: LEKA's default policy.")


class ApprovalPolicyUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approvals: dict[Level, int] = Field(default_factory=dict)
    separate: list[Level] | None = None
    production_raises: bool | None = None
    roles: dict[Level, Literal["admin", "owner"] | None] | None = None
    valid_hours: dict[Level, int | None] | None = None
    escalate_hours: dict[Level, int | None] | None = None
    rules: list[RiskRuleRead] | None = Field(default=None, max_length=30)


class PolicyProbe(BaseModel):
    """An action as it could be proposed: what the policy would say of it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(min_length=1, max_length=40)
    environment: str | None = Field(default=None, max_length=60)
    targets: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    risk: Literal["high", "medium", "low"] | None = Field(
        default=None, description="The analysis's, when one said; none: LEKA cannot say."
    )


class PolicyVerdictRead(BaseModel):
    """What the policy says of an action, now."""

    model_config = ConfigDict(frozen=True)

    risk: Literal["low", "medium", "high", "critical"]
    reasons: list[dict[str, JsonValue]]
    approvals: int
    separate: bool
    role: str | None
    valid_hours: int | None
    escalate_hours: int | None
    frozen: bool
    waived: bool
    exceptions: list[dict[str, JsonValue]]


class GovernanceExceptionRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    kind: Literal["freeze", "waiver"]
    actions: list[str]
    environments: list[str]
    targets: list[uuid.UUID]
    max_risk: Literal["low", "medium", "high", "critical"]
    starts_at: datetime
    ends_at: datetime
    reason: str
    granted_by: uuid.UUID | None
    revoked_at: datetime | None
    revoked_by: uuid.UUID | None
    active: bool = False


class GovernanceExceptionCreate(BaseModel):
    """A freeze — what it covers is not approved nor run — or a waiver —
    what it covers, up to a medium risk, is approved by the policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["freeze", "waiver"]
    reason: str = Field(min_length=3, max_length=2000)
    starts_at: datetime | None = Field(default=None, description="None: now.")
    ends_at: datetime
    actions: list[str] = Field(default_factory=list, max_length=20)
    environments: list[str] = Field(default_factory=list, max_length=20)
    targets: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    max_risk: Literal["low", "medium"] = "low"


class DelegationRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    delegated_by: uuid.UUID
    delegated_to: uuid.UUID
    max_risk: Literal["low", "medium", "high", "critical"]
    starts_at: datetime
    ends_at: datetime
    reason: str
    revoked_at: datetime | None
    revoked_by: uuid.UUID | None
    active: bool = False


class DelegationCreate(BaseModel):
    """Your authority to approve, lent to a member: up to a risk, for a
    time, said why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    to: uuid.UUID
    max_risk: Literal["low", "medium", "high", "critical"]
    reason: str = Field(min_length=3, max_length=2000)
    starts_at: datetime | None = Field(default=None, description="None: now.")
    ends_at: datetime


class DecisionGovernanceEventRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    kind: str
    by: uuid.UUID | None
    at: datetime
    subject_id: uuid.UUID | None
    detail: dict[str, JsonValue]


class DecisionVoteRequest(BaseModel):
    """A vote: why — required to reject, modify or ask for changes — and,
    to modify, where it should run and which actions are kept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)
    environment: str | None = Field(default=None, min_length=1, max_length=60)
    keep: list[str] | None = Field(default=None, max_length=20)
    on_behalf_of: uuid.UUID | None = Field(
        default=None,
        description="Vote with this approver's authority, which they delegated to you (LEKA-404).",
    )


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


class ExpectationRead(BaseModel):
    """What should be true once it ran (LEKA-392)."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(max_length=200)
    kind: Literal["healthy", "incident_resolved", "metric", "confirmed"]
    target: dict[str, str] | None = None
    name: str | None = Field(default=None, max_length=100)
    comparator: Literal["lt", "lte", "eq", "gte", "gt"] | None = None
    value: JsonValue = None
    source: Literal["model", "system"] = "model"
    said: str | None = Field(default=None, max_length=500)
    incidents: list[str] = Field(default_factory=list)


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
    expectations: list[ExpectationRead] = Field(
        description="What should be true once it ran (LEKA-392)."
    )
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


# ── outcomes (LEKA-392) ──────────────────────────────────────────────────────


class ObservedResultRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    expectation_id: str
    seen: Literal["met", "not_met", "unknown", "awaiting"]
    value: JsonValue = None
    detail: str | None = None
    reported: dict[str, JsonValue] | None = None


class IntentionVerificationRead(BaseModel):
    """Whether what ran achieved what was expected."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    intention_id: uuid.UUID
    plan_id: uuid.UUID
    status: Literal["verifying", "succeeded", "partial", "failed"]
    expectations: list[ExpectationRead]
    results: list[ObservedResultRead]
    observe_after: datetime
    deadline: datetime
    observed_at: datetime | None
    concluded_at: datetime | None
    concluded_by: uuid.UUID | None
    context_update: dict[str, JsonValue]
    # A person's note, when a person concluded it.
    detail: dict[str, JsonValue]
    created_at: datetime


class ExpectationsUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expectations: list[ExpectationRead] = Field(max_length=30)


class ExpectationReport(BaseModel):
    """A person's word on one expectation, and what shows it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    met: bool
    note: str = Field(min_length=1, max_length=2000)
    link: HttpUrl | None = Field(default=None, description="http or https only.")


class VerificationConclude(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    note: str = Field(min_length=1, max_length=2000)


class TimelineItem(BaseModel):
    """One moment of an intention's story: what happened, of which kind —
    the intention, its analysis, its decision, its action, its outcome — by
    whom, when."""

    model_config = ConfigDict(frozen=True)

    id: str
    intention_id: uuid.UUID
    title: str | None = Field(default=None, description="The intention's — across intentions.")
    category: Literal["intention", "analysis", "decision", "action", "outcome"]
    kind: str
    at: datetime
    actor: Literal["person", "system"]
    by: uuid.UUID | None = None
    by_name: str | None = Field(
        default=None, description="Their name — their address when they gave none."
    )
    reason: str | None = None
    detail: dict[str, JsonValue] = Field(default_factory=dict)
