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
from leka.context import AssembledContext, IntentAsk
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
    # LEKA-434: an action negated in part, conditional or doubtful.
    "ambiguous_action",
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
    polarity: Literal["affirmed", "negated", "conditional", "ambiguous"] = Field(
        default="affirmed",
        description="Whether it is asked (LEKA-434): affirmed; negated (« ne redémarre pas »); "
        "conditional (« si … »); ambiguous (a negation not on it).",
    )
    targets: list[uuid.UUID] = Field(
        default_factory=list,
        description="The things it is on, as said with it (LEKA-434); empty: not said.",
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


class AmbiguityChoice(BaseModel):
    """One thing an answer may name, by id (LEKA-439): a thing of the company
    model the words could mean."""

    model_config = ConfigDict(frozen=True)

    value: str = Field(description="What the answer gives back: the thing's id.")
    label: str
    type: str | None = None


class AmbiguityRead(BaseModel):
    """What LEKA cannot tell, and what it would ask to tell it."""

    model_config = ConfigDict(frozen=True)

    kind: AmbiguityKind
    blocking: bool = Field(description="It cannot go on without an answer.")
    said: str = Field(description="What is ambiguous, in English.")
    options: list[str] = Field(
        default_factory=list, description="What it could mean: things, goals."
    )
    choices: list[AmbiguityChoice] = Field(
        default_factory=list,
        description="The things it could mean, by id — chosen, the answer narrows it to "
        "one (LEKA-439).",
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
    actions: list[ActionRead] = Field(description="What is asked to be done.")
    withheld: list[ActionRead] = Field(
        default_factory=list,
        description="Actions spoken of but not asked — negated, conditional, doubtful "
        "(LEKA-434): never proposed.",
    )
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


# ── its brief (LEKA-439) ─────────────────────────────────────────────────
# What LEKA must know to work on an intention, what it knows of it, what it
# asks — docs/intentions.md § 9 bis.

Slot = Literal["goal", "target", "scope", "expected", "constraints"]
SlotState = Literal["known", "assumed", "missing", "unknown"]
SlotNeed = Literal["blocking", "useful", "optional"]
BriefDecision = Literal["analyse", "clarify", "continue", "block"]
Expected = Literal["answer", "document", "plan", "action"]


class IntentionAnswer(BaseModel):
    """What its asker answered to one of LEKA's questions (LEKA-439): a
    choice, their own words, or « je ne sais pas »."""

    model_config = ConfigDict(frozen=True)

    question: AmbiguityKind
    value: str | None = Field(
        default=None, max_length=300, description="A choice's value, or their words."
    )
    unknown: bool = Field(default=False, description="« Je ne sais pas »: said, never guessed.")


class IntentionRequest(IntentAsk):
    """An intention asked, with what its asker answered to LEKA's questions
    (LEKA-439): kept, and read again with it."""

    answers: list[IntentionAnswer] = Field(default_factory=list, max_length=20)


class BriefSlotRead(BaseModel):
    """One part of what LEKA must know (LEKA-439), and what it knows of it."""

    model_config = ConfigDict(frozen=True)

    slot: Slot
    state: SlotState = Field(
        description="known: said or answered; assumed: LEKA's reading, never a fact; "
        "missing: not said; unknown: its asker does not know."
    )
    need: SlotNeed = Field(description="Whether LEKA can go on without it.")
    value: str | None = Field(description="A code — a goal, what is expected — or a word.")
    values: list[str] = Field(default_factory=list, description="Things, constraints.")
    origin: Literal["words", "answer", "model", "company_model", "default"] | None


class BriefQuestionRead(BaseModel):
    """What LEKA asks (LEKA-439): about which part, whether it stops it, what
    it could be — and what was answered."""

    model_config = ConfigDict(frozen=True)

    kind: AmbiguityKind
    slot: Slot
    blocking: bool
    said: str = Field(description="What is ambiguous, in English: the screen says it in words.")
    options: list[str]
    choices: list[AmbiguityChoice]
    free: bool = Field(description="Its asker may answer in their own words.")
    answer: IntentionAnswer | None


class IntentionBrief(BaseModel):
    """An intention's brief (LEKA-439): the contract of what LEKA must know,
    each part's state, its questions in order, and what follows — analyse,
    clarify, continue with its limits said, or block."""

    model_config = ConfigDict(frozen=True)

    version: int
    decision: BriefDecision
    restated: str | None
    acting: bool = Field(description="It asks to change systems: never on a doubt.")
    slots: list[BriefSlotRead]
    questions: list[BriefQuestionRead]
    limits: list[AmbiguityKind] = Field(
        description="What it goes on without, said: unanswered, or not known."
    )


# ── what it takes to carry it through (LEKA-439) ─────────────────────────

OfferStatus = Literal["included", "beta", "add_on", "planned"]
Verdict = Literal["ready", "prerequisites", "over_quota", "impossible"]
PathKind = Literal[
    "connect_source",
    "configure_model",
    "ask_admin",
    "enable",
    "buy_pack",
    "buy_add_on",
    "buy_bundle",
    "change_plan",
    "contact_sales",
    "rephrase",
]


class NeededRead(BaseModel):
    """A capability it needs, as this workspace may use it (LEKA-439)."""

    key: str
    title: str
    kind: str
    offer: OfferStatus = Field(
        description="included; beta — usable, sold later; add_on — bought; planned — not yet."
    )
    available: bool = Field(description="Usable here, by this person, now.")
    reasons: list[dict[str, JsonValue]] = Field(description="Why not: code and detail.")
    delivers: str = Field(description="finding, analysis, document, proposal.")
    selected: bool = Field(description="It will run: routed to, or always.")
    essential: bool = Field(
        description="Routed to: without it, it is not carried through. What always runs only "
        "adds to it."
    )
    credits: float | None = Field(description="What one run of it has cost here, median.")
    price: int | None = Field(default=None, description="An add-on's monthly price, cents.")


class PathStepRead(BaseModel):
    """One thing it takes — cheapest first; never done without a yes when it
    costs money (LEKA-439)."""

    kind: PathKind
    detail: dict[str, JsonValue]
    consent: bool = Field(description="It costs money or changes a plan: asked first.")


class CreditsLeftRead(BaseModel):
    """A workspace's AI credits this month, as it bears on carrying an
    intention through (metering, LEKA-430)."""

    plan: Literal["free", "starter", "growth", "business", "enterprise"]
    allowance: int
    used: float
    remaining: float
    state: Literal["ok", "warning", "exhausted"]
    enforced: bool = Field(description="Spent, LEKA's models are refused until the month ends.")
    period_end: datetime


class FeasibilityRead(BaseModel):
    """What it takes to carry it through (LEKA-439): the capabilities, the
    credits, the verdict, the least it takes."""

    verdict: Verdict
    needed: list[NeededRead]
    credits: CreditsLeftRead
    estimate: float | None = Field(description="What it should cost, credits; none: not known.")
    path: list[PathStepRead]


class SourceToReadRead(BaseModel):
    """A source LEKA will read for it."""

    id: uuid.UUID
    name: str
    kind: str
    status: str


class IntentionPreview(BaseModel):
    """What LEKA would make of an intention before it is asked (LEKA-439):
    what it understood, its brief, what it would read, what it takes —
    nothing kept."""

    understanding: Understanding
    brief: IntentionBrief
    sources: list[SourceToReadRead]
    feasibility: FeasibilityRead


class IntentionAnswers(BaseModel):
    """What its asker answers to LEKA's questions (LEKA-439)."""

    answers: list[IntentionAnswer] = Field(min_length=1, max_length=20)


class IntentionDetail(IntentionRead):
    """An intention with what it is linked to, and what LEKA understood."""

    links: list[IntentionLinkRead]
    understanding: Understanding | None
    readiness: ContextReadiness | None = Field(
        default=None, description="Whether its context can ground its analysis (LEKA-387)."
    )
    answers: list[IntentionAnswer] = Field(
        default_factory=list, description="What its asker answered to LEKA (LEKA-439)."
    )
    brief: IntentionBrief | None = Field(
        default=None, description="What LEKA knows and asks of it (LEKA-439)."
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
    strength: Literal["confirmed", "probable", "correlated"] | None = Field(
        default=None,
        description="confirmed — its source says so; probable — LEKA infers it with enough to "
        "go on; correlated — only time ties it to what happened, never called a cause "
        "(LEKA-441). None on an analysis made before.",
    )


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


class AnalysisPrecondition(BaseModel):
    """What must hold before a recommendation can be carried out (LEKA-441)."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(
        description="precondition.version_to_restore, precondition.environment, "
        "precondition.cause_confirmed, precondition.approved — worded by the interface."
    )
    text: str
    met: bool | None = Field(description="None: not known yet — an approval to come.")
    blocking: bool = Field(description="Unmet, it cannot be carried out as it stands.")
    params: dict[str, JsonValue] = Field(default_factory=dict)


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
    preconditions: list[AnalysisPrecondition] = Field(
        default_factory=list, description="What must hold first (LEKA-441)."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="The causes it rests on that are not confirmed: what it assumes.",
    )
    executable: bool | None = Field(
        default=None,
        description="Every blocking precondition met; None on an analysis made before.",
    )


# ── what an analysis rests on, said (LEKA-441) ─────────────────────────────


class ExplainedSource(BaseModel):
    """A source behind what the analysis read — and in what state it was
    when it read: never shown as read when it was not."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    kind: str | None
    name: str | None
    elements: int = Field(description="What of its context came from it.")
    state: Literal["read", "error", "degraded", "stale", "syncing", "disabled", "gone"] = Field(
        description="read — synced and well; error, degraded — failing, what it said is as of "
        "its last sync; stale — not synced for STALE_DAYS; syncing — still reading when the "
        "analysis ran; disabled; gone — deleted since."
    )
    last_synced_at: datetime | None
    said: str = Field(description="In English, for what reads it without a dictionary.")


class ExplainedCapability(BaseModel):
    """A capability chosen, how it went — and, when it did not answer, what
    is not known because of it."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: Literal["succeeded", "failed", "timed_out", "skipped"]
    reason: str | None
    leaves: AnalysisNote | None = Field(description="What is not known because it did not answer.")


class ConfidenceReason(BaseModel):
    """One reason for how sure it is: what it starts from, what raises or
    lowers it, what caps it."""

    model_config = ConfigDict(frozen=True)

    code: str
    effect: Literal["base", "raises", "lowers", "caps"]
    text: str
    params: dict[str, JsonValue] = Field(default_factory=dict)


class ExplainedConfidence(BaseModel):
    """How sure the analysis is — in words, with why; never a bare figure."""

    model_config = ConfigDict(frozen=True)

    level: Literal["high", "medium", "low", "unknown"]
    reasons: list[ConfidenceReason]


class AnalysisClaim(BaseModel):
    """A figure the screen may say — « 3 sources à l'appui », « 2
    événements corrélés », « 0 contradiction » — what it counts, and what it
    is read from: none said that is not counted."""

    model_config = ConfigDict(frozen=True)

    code: Literal["sources", "correlated_events", "contradictions", "impacted_users"]
    count: int
    holds: bool = Field(description="It supports the conclusion: sources behind it, no conflict.")
    definition: str = Field(description="What it counts, in English.")
    refs: list[str] = Field(
        description="What it was counted from: source ids, evidence ids, conflict ids."
    )


class ExplainedConflict(BaseModel):
    """What its sources disagree on, about what it asks: every side, who
    says it."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    about: str
    values: list[dict[str, JsonValue]] = Field(description="Each {value, by}.")
    said: str


class AnalysisNextStep(BaseModel):
    """What to do next, and why that."""

    model_config = ConfigDict(frozen=True)

    code: Literal[
        "decide",
        "prepare",
        "settle_conflict",
        "confirm_cause",
        "ask_differently",
        "rerun",
        "fix_source",
        "act",
        "nothing",
    ]
    text: str
    why: AnalysisNote
    params: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisExplanation(BaseModel):
    """On what an analysis rests (LEKA-441): what LEKA understood, what it
    really read and in what state, what failed and what that leaves unknown,
    how sure it is and why, the figures it may say with what they count,
    what disagrees, what is stale, its limits, and what to do next."""

    model_config = ConfigDict(frozen=True)

    understood: AnalysisNote
    consulted: list[ExplainedSource]
    capabilities: list[ExplainedCapability]
    confidence: ExplainedConfidence
    claims: list[AnalysisClaim]
    conflicts: list[ExplainedConflict]
    stale: list[AnalysisNote]
    limits: list[AnalysisNote]
    next: AnalysisNextStep
    context_version: int | None = Field(description="The version of its context it read.")


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
    explanation: AnalysisExplanation | None = Field(
        default=None,
        description="On what it rests (LEKA-441); none on an analysis made before.",
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
    context_now: int | None = Field(
        default=None,
        description="The version its intention's context is at now: newer than "
        "`context_version`, the analysis read an older one — said, never silently kept "
        "(LEKA-441).",
    )


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


class DecisionGroundingRead(BaseModel):
    """What an action asked rests on, when something it needs is missing
    (LEKA-436)."""

    model_config = ConfigDict(frozen=True)

    gate: Literal["blocked", "validation"] = Field(
        description="blocked: high or critical risk, not approvable until analysed again; "
        "validation: one more approval than the policy asks."
    )
    missing: list[str] = Field(
        description="The capabilities whose evidence it needs that did not succeed: "
        "standing, action, changes, ownership."
    )
    stale: list[str] = Field(
        description="What in its context is stale: model_stale, stale_evidence."
    )


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
    grounding: DecisionGroundingRead | None = Field(
        default=None, description="Set when what it rests on is missing or stale (LEKA-436)."
    )


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
