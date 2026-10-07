"""What the intelligence API says (LEKA-377): the analyses there are, the
runs and what each analysis of them did, the findings and what shows them
— and the enrichments of the company model proposed, and what was decided
of them (LEKA-380); what its sources disagree on, and the workspace's word
on how much each is to be believed (LEKA-382).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

SeverityName = Literal["high", "medium", "low"]
FindingStatus = Literal["open", "resolved"]
CandidateStatus = Literal["proposed", "accepted", "rejected", "withdrawn"]
ConflictStatus = Literal["open", "resolved", "dismissed", "gone"]


class AnalyzerRead(BaseModel):
    """One analysis LEKA runs: what it reads, how it reasons, whether it can
    run here and now."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    category: str = Field(description="architecture, organisation, context, changes, gaps.")
    method: Literal["rules", "model"]
    reads: list[Literal["model", "context", "changes", "conflicts", "evolution"]]
    summary: str = Field(description="What it looks for (English).")
    available: bool = Field(description="False for a model-assisted one: no model gateway yet.")


class AnalysisRequest(BaseModel):
    """Analyse now. Every analysis, or those named."""

    model_config = ConfigDict(extra="forbid")

    analyzers: list[str] | None = Field(
        default=None, max_length=50, description="Their names; none: every one."
    )


class AnalysisRequested(BaseModel):
    """`queued` is false when a run is already on its way: it will be the
    one that answers."""

    model_config = ConfigDict(frozen=True)

    queued: bool


class StepRead(BaseModel):
    """One analysis of a run: what it did, or why it did not."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    analyzer: str
    version: int
    status: Literal["succeeded", "failed", "timed_out", "skipped"]
    started_at: datetime
    duration_ms: int
    counts: dict[str, int] = Field(description="found, opened, seen (again), resolved, reopened.")
    error: str | None = Field(description="Failed or timed out: the error's type.")
    reason: str | None = Field(description="Skipped: no_model, no_material.")


class RunRead(BaseModel):
    """One time LEKA analysed the workspace."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    status: Literal["running", "succeeded", "partial", "failed", "abandoned"]
    trigger: Literal["model", "schedule", "request"]
    requested_by: uuid.UUID | None
    requested: list[str] = Field(description="The analyses asked for; empty: every one.")
    started_at: datetime
    finished_at: datetime | None
    model_built_at: datetime | None = Field(description="The build of the model it read.")
    job_run_id: uuid.UUID | None = Field(description="The background job that ran it.")
    counts: dict[str, int]
    error: str | None


class RunDetail(RunRead):
    steps: list[StepRead]


class SubjectRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["entity", "context", "source", "coverage", "column", "workspace"] = Field(
        description="An entity, a context, a source (LEKA-379) — or a family of sources: "
        "coverage; a column of Mon environnement, or the workspace (LEKA-381)."
    )
    id: uuid.UUID | None
    name: str
    kind: str | None


class EvidenceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str = Field(description="entity, relationship, context.")
    id: str | None
    name: str
    detail: str = Field(description="What it shows (English).")


class FindingRead(BaseModel):
    """What an analysis concluded about one thing."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    analyzer: str
    analyzer_version: int
    category: str
    code: str = Field(description="What it says, for the interface to word.")
    params: dict[str, object] = Field(description="The values the code is worded with.")
    statement: str = Field(description="What it says, in English.")
    severity: SeverityName
    rank: int = Field(description="Its place: severity first (300s high), then its weight.")
    confidence: float
    subject: SubjectRead
    status: FindingStatus
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    occurrences: int = Field(description="How many runs saw it.")


class FindingDetail(FindingRead):
    """And what shows it, where that was read, which runs saw it."""

    related: list[SubjectRead]
    evidence: list[EvidenceRead]
    provenance: dict[str, object] = Field(
        description="The build of the model, the sources' kinds, the context version, "
        "the analysis and its version."
    )
    first_run_id: uuid.UUID
    last_run_id: uuid.UUID
    resolved_run_id: uuid.UUID | None
    reopened: int


class IntelligenceSummary(BaseModel):
    """Where the workspace's analysis stands: what is open, how bad, the
    most pressing — for a product surface to show at a glance."""

    model_config = ConfigDict(frozen=True)

    open: dict[str, int] = Field(description="The open findings, by severity.")
    top: list[FindingRead] = Field(description="The most pressing open ones.")
    latest: RunRead | None = Field(description="The latest run, whatever came of it.")


# ── change and impact (LEKA-378) ───────────────────────────────────────


class ImpactRead(BaseModel):
    """One thing a change reaches, and why it ranks there."""

    model_config = ConfigDict(frozen=True)

    subject: SubjectRead
    distance: int = Field(description="0: made to it; 1, 2: depends on that, steps away.")
    score: float
    reasons: list[str] = Field(description="touched, depends_on:<what>, holds, incident, critical.")


class FollowedRead(BaseModel):
    """An incident after a change, or that its source says it caused."""

    model_config = ConfigDict(frozen=True)

    subject: SubjectRead
    opened_at: datetime | None
    hours_after: float | None
    severity: str | None
    state: str | None
    on: SubjectRead | None = Field(description="What of the change's footprint it affects.")
    stated: bool = Field(description="Its source says the change caused it.")


class ChangeImpactRead(BaseModel):
    """A change, judged: what kind, when, current or history, how much it
    matters and why, what it was made to, how far it reaches."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    kind: Literal["deployment", "change", "release", "pull_request"]
    at: datetime
    state: str | None
    environment: str | None
    current: bool = Field(description="Within 72 hours: still playing out. Else history.")
    significance: float = Field(description="0 to 1.")
    signals: list[str] = Field(
        description="production, failed, incident_after, stated_cause, wide, business, critical."
    )
    touched: list[SubjectRead]
    reached: int
    incidents: int
    top: list[ImpactRead] = Field(description="The three most affected.")
    sources: list[str]


class ChangeImpactDetail(ChangeImpactRead):
    """And everything it reaches, ranked; the business; what followed;
    what its source says of it."""

    details: dict[str, str]
    source_ids: list[str]
    impacts: list[ImpactRead]
    applications: list[SubjectRead]
    capabilities: list[SubjectRead]
    processes: list[SubjectRead]
    followed: list[FollowedRead]


class ChangeImpactTimeline(BaseModel):
    """The changes between two dates, the latest first."""

    model_config = ConfigDict(frozen=True)

    since: datetime
    until: datetime
    around: uuid.UUID | None = Field(description="The entity they were made to or around.")
    changes: list[ChangeImpactRead]
    truncated: bool


# ── enrichment (LEKA-380) ──────────────────────────────────────────────


class CandidateRead(BaseModel):
    """An enrichment of the company model LEKA proposed: a relationship or
    an attribute, how sure, and where it stands."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    analyzer: str
    family: str = Field(description="relationship, semantic, organisation, business.")
    code: str = Field(description="What it proposes, for the interface to word.")
    method: Literal["rules", "model"]
    kind: Literal["relationship", "attribute"]
    subject: SubjectRead = Field(description="The thing it enriches.")
    relationship: str | None = Field(description="The relationship's kind, from start to end.")
    start: SubjectRead | None
    end: SubjectRead | None
    attribute: str | None
    value: JsonValue = Field(description="The attribute's value proposed.")
    current: JsonValue = Field(description="What the model said of that attribute then.")
    overrides: bool = Field(
        description="Accepting it replaces what a source says: only a person may, saying so."
    )
    statement: str = Field(description="What it proposes, in English.")
    params: dict[str, object] = Field(description="The values the code is worded with.")
    confidence: float
    status: CandidateStatus
    decided_via: Literal["person", "policy"] | None
    decided_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int


class CandidateDetail(CandidateRead):
    """And what shows it, where that was read, and every decision taken."""

    evidence: list[EvidenceRead]
    provenance: dict[str, object] = Field(
        description="The build of the model, the sources' kinds, the analysis and its version."
    )
    decided_by: uuid.UUID | None
    reason: str | None
    history: list[dict[str, object]] = Field(
        description="Every decision: {status, via, by, at, reason}, the latest last."
    )


class EnrichmentSummary(BaseModel):
    """Where the workspace's enrichment stands: how many wait, were
    accepted — by a person, by the policy — were rejected or withdrawn."""

    model_config = ConfigDict(frozen=True)

    proposed: int
    accepted: int
    rejected: int
    withdrawn: int
    by_policy: int = Field(description="Of those accepted, by the workspace's policy.")
    families: dict[str, int] = Field(description="Those waiting, by family.")


class Decision(BaseModel):
    """Accept or reject a candidate."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)
    override: bool = Field(
        default=False,
        description="Accept a candidate that replaces what a source says: required for one.",
    )


class Reprocessed(BaseModel):
    """A candidate sent back to its analysis: proposed again if its evidence
    still holds, withdrawn otherwise — `queued` false when a run was
    already on its way, which will do it."""

    model_config = ConfigDict(frozen=True)

    candidate: CandidateRead
    queued: bool


# ── conflicts (LEKA-382) ───────────────────────────────────────────────


class ConflictSourceRead(BaseModel):
    """A source saying one side: how much it is believed on this, and why."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID | None
    kind: str | None
    name: str | None
    status: str | None
    observed_at: datetime | None = Field(description="When it last said this value.")
    authority: float = Field(description="0 to 1: its family's, or the workspace's rule.")
    rule: Literal["prefer", "avoid"] | None = Field(description="The workspace's word on it.")


class ConflictSideRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: JsonValue
    ref_id: uuid.UUID | None = Field(description="For a relationship: the other end.")
    origin: str | None = Field(description="For a relationship: stated, inferred, accepted.")
    sources: list[ConflictSourceRead]
    authority: float
    freshness: float
    corroboration: float
    score: float = Field(description="0.55 authority + 0.3 freshness + 0.15 corroboration.")


class RecommendationRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    side: int | None = Field(description="The side recommended; none when none stands out.")
    strength: Literal["rule", "clear", "weak", "none"]
    reasons: list[str] = Field(description="rule, authority, fresher, corroborated, chosen.")
    margin: float


class ConflictRead(BaseModel):
    """What the model's sources disagree on, every side weighed, what LEKA
    recommends, where it stands."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    kind: Literal["attribute", "relationship"]
    subject: SubjectRead
    about: str = Field(description="The attribute, or the relationship's role: owner, manager.")
    relationship: str | None
    chosen: JsonValue = Field(description="What the model shows now, for an attribute.")
    sides: list[ConflictSideRead]
    recommendation: RecommendationRead
    statement: str = Field(description="The disagreement and the recommendation, in English.")
    status: ConflictStatus
    resolution: dict[str, object] | None = Field(
        description="The decision standing: {side, value, via, by, at, reason}."
    )
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int


class ConflictDetail(ConflictRead):
    provenance: dict[str, object]
    history: list[dict[str, object]] = Field(
        description="Every decision and change: {status, via, by, at, reason, value}."
    )


class ConflictSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    open: int
    resolved: int
    dismissed: int
    gone: int


class Arbitration(BaseModel):
    """Keep one side."""

    model_config = ConfigDict(extra="forbid")

    side: int = Field(ge=0, description="The side kept, by its place in `sides`.")
    reason: str | None = Field(default=None, max_length=500)
    remember: bool = Field(
        default=False,
        description="Prefer this side's source on this from now on: an authority rule.",
    )


class Dismissal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class AuthorityRuleRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    about: str = Field(description="An attribute, a role, or `*`: everything.")
    source_id: uuid.UUID
    source_name: str | None
    source_kind: str | None
    stance: Literal["prefer", "avoid"]
    reason: str | None
    created_by: uuid.UUID | None
    created_at: datetime


class AuthorityRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    about: str = Field(min_length=1, max_length=100, pattern=r"^(\*|[a-z_][a-z0-9_]*)$")
    source_id: uuid.UUID
    stance: Literal["prefer", "avoid"]
    reason: str | None = Field(default=None, max_length=500)


# ── knowledge quality (LEKA-381) ───────────────────────────────────────


class KnowledgeQualityPoint(BaseModel):
    """A score at one moment: when it moved, where to."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    measured_at: datetime
    score: float
    level: Literal["high", "medium", "low"]
    completeness: float | None
    freshness: float | None
    consistency: float | None
    confidence: float | None


class KnowledgeQualityRead(BaseModel):
    """How far what LEKA knows of one thing, or one area, can be trusted."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(
        description="entity:<id>, team:<id>, application:<id>, column:<name>, workspace."
    )
    scope: Literal["entity", "team", "application", "column", "workspace"]
    subject: SubjectRead
    column: str | None = Field(description="An entity's column of Mon environnement.")
    score: float = Field(
        description="0 to 1: .30 completeness + .25 freshness + .20 consistency "
        "+ .25 confidence, over the dimensions known."
    )
    level: Literal["high", "medium", "low"] = Field(description="high from 0.85, medium from 0.6.")
    completeness: float | None
    freshness: float | None
    consistency: float | None
    confidence: float | None
    missing: list[dict[str, JsonValue]] = Field(
        description="What lowers it, the heaviest first: {code, dimension, weight, detail} — "
        "an area's: {code, count}."
    )
    areas: list[str] = Field(description="An entity's: the areas it counts in.")
    entities: int = Field(description="An area's: how many things it holds.")
    capped: str | None = Field(
        description="Held to medium: contradiction — one left open; weak_dimension — a "
        "dimension measured under 0.6."
    )
    measured_at: datetime
    since: datetime = Field(description="Since when it holds its level.")


class KnowledgeQualityDetail(KnowledgeQualityRead):
    """One score: each dimension's factors, where it was read, its history."""

    factors: dict[str, JsonValue]
    provenance: dict[str, JsonValue]
    history: list[KnowledgeQualityPoint] = Field(description="Its changes, the oldest first.")


class KnowledgeQualitySummary(BaseModel):
    """The workspace's knowledge quality at a glance: where it stands, by
    area, the things known least well, and how it moved."""

    model_config = ConfigDict(frozen=True)

    measured_at: datetime | None
    workspace: KnowledgeQualityRead | None
    levels: dict[str, int] = Field(description="The things measured, by level.")
    columns: list[KnowledgeQualityRead]
    teams: list[KnowledgeQualityRead]
    applications: list[KnowledgeQualityRead]
    weakest: list[KnowledgeQualityRead]
    trend: list[KnowledgeQualityPoint] = Field(description="The workspace's, over 30 days.")
    change: float | None = Field(description="The workspace's score now, less 7 days ago.")


# ── the activity (LEKA-383) ──────────────────────────────────────────────────

ActivityCategory = Literal["information", "action", "alert", "incident"]
ActivityKind = Literal[
    "model_built",
    "entity_removed",
    "incident",
    "deployment",
    "change",
    "release",
    "analysis",
    "finding",
    "proposal",
    "decision",
    "conflict",
    "conflict_decision",
    "restore",
    "rebuild",
    "undo",
    "source_event",
]


class ActivityCount(BaseModel):
    """A count over the period, and over the period before."""

    model_config = ConfigDict(frozen=True)

    value: int
    previous: int


class ActivityStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: ActivityCount = Field(description="Everything that happened, counted one by one.")
    actions: ActivityCount = Field(description="What LEKA did, and what people decided.")
    incidents: ActivityCount
    waiting: int = Field(description="What waits in À valider now.")
    people: ActivityCount = Field(description="The people who decided something.")


class ActivityBucket(BaseModel):
    """One day, in the reader's zone: how much of each category."""

    model_config = ConfigDict(frozen=True)

    day: date
    information: int = 0
    action: int = 0
    alert: int = 0
    incident: int = 0


class ActivityItem(BaseModel):
    """One thing that happened."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Stable: its kind and what it is — model:<run>, finding:<id>.")
    at: datetime
    category: ActivityCategory = Field(
        description="information: the model and the systems moved; action: LEKA did, someone "
        "decided; alert: LEKA raised something; incident."
    )
    kind: ActivityKind
    count: int = Field(description="How many events it stands for: a build's changes.")
    subject: SubjectRead | None
    params: dict[str, JsonValue] = Field(description="What the interface words it from.")
    by: uuid.UUID | None
    by_name: str | None
    via: Literal["person", "policy", "leka", "source"]


class ActivityTop(BaseModel):
    """A service or an application, and how much concerned it."""

    model_config = ConfigDict(frozen=True)

    subject: SubjectRead
    count: int
    previous: int


class ActivityPerson(BaseModel):
    """Someone who decided, and how often."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    name: str
    role: str | None
    count: int
    previous: int


class ActivityRead(BaseModel):
    """What happened in the environment and what LEKA did, over a period —
    and the period before, as long (LEKA-383)."""

    model_config = ConfigDict(frozen=True)

    since: datetime
    until: datetime
    timezone: str
    stats: ActivityStats
    buckets: list[ActivityBucket]
    categories: dict[str, int] = Field(description="How much of each category, the period.")
    latest: list[ActivityItem] = Field(description="The latest first.")
    top: list[ActivityTop] = Field(description="The services and applications most concerned.")
    people: list[ActivityPerson] = Field(description="Those who decided most.")
