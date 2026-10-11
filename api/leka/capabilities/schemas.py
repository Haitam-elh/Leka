"""The contract an agent file must satisfy.

An agent is a markdown file with YAML front matter (see
docs/adr/004-agents-as-markdown.md). There is no compiler between a typo and
production, so this model is what stands in its place: it is strict on
purpose, and it refuses rather than guesses.
"""

from __future__ import annotations

import enum
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, field_validator

from leka.connectors import PublicHttpsUrl

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
VENDOR_ORIGIN_PATTERN = re.compile(r"^vendor:[\w.-]+/[\w.-]+$")


class AgentMode(enum.StrEnum):
    """What an agent is allowed to do.

    PROPOSES_ACTION does not mean "may act". It means the agent may produce
    a proposal, which leka.intentions executes only after a named,
    timestamped human approval.
    """

    READ_ONLY = "read_only"
    PROPOSES_ACTION = "proposes_action"


class AgentRisk(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentInput(BaseModel):
    """One thing an agent takes (LEKA-393): what its contract says it needs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: str = "text"
    required: bool = True
    description: str = ""
    choices: tuple[str, ...] = ()
    entity_types: tuple[str, ...] = ()


class AgentFrontMatter(BaseModel):
    """The YAML header of a SKILL.md file."""

    # extra="forbid": an unknown key is a typo in a field that decides
    # whether an agent triggers, or how it is allowed to behave. Silence is
    # not an option here.
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Unique identifier, kebab-case")
    description: str = Field(
        min_length=20,
        description=(
            "One sentence saying WHEN to use this agent. The most important "
            "field: it is what decides whether the agent triggers at all."
        ),
    )
    version: str
    entity_types: tuple[str, ...] = Field(min_length=1)
    requires: tuple[str, ...] = Field(
        default=(), description="Connectors that must be connected for it to run"
    )
    mode: AgentMode
    risk: AgentRisk
    outputs: str = Field(description="The kind of finding it produces")
    origin: str = Field(description="'internal' or 'vendor:<owner>/<repo>'")
    # What the catalogue says of it, and what routes to it (LEKA-393).
    title: str | None = Field(default=None, description="How people call it; its name otherwise")
    category: str = Field(description="What it is about: architecture, development, data…")
    inputs: tuple[AgentInput, ...] = Field(default=(), description="What it takes")
    deliverables: tuple[str, ...] = Field(
        default=(), description="The formats it delivers: pptx, pdf, markdown…"
    )
    goals: tuple[str, ...] = Field(default=(), description="The intentions' goals it answers")
    kinds: tuple[str, ...] = Field(default=(), description="The kinds of intention it answers")
    examples: tuple[str, ...] = Field(default=(), description="How people ask for it")
    permission: str = Field(default="intention:create", description="What a person needs to use it")
    tools: tuple[str, ...] = Field(
        default=(),
        description="The tools it may be offered (LEKA-400); every read-only one when none",
    )
    skills: tuple[str, ...] = Field(
        default=(),
        description="The skills it may be offered (LEKA-401): none unless named, each within "
        "the kinds of things it may read",
    )
    renders: Literal["architecture_deck", "code_change"] | None = Field(
        default=None,
        description="What LEKA makes of what it delivers: architecture_deck — the editable "
        "PowerPoint and its PDF, on the application architecture template; code_change — "
        "the change it proposes, diffed, for a person to accept as a pull request",
    )

    @field_validator("name")
    @classmethod
    def _kebab_case(cls, value: str) -> str:
        if not NAME_PATTERN.match(value):
            msg = f"name must be kebab-case, got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("skills")
    @classmethod
    def _skill_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        wrong = [key for key in value if not NAME_PATTERN.match(key)]
        if wrong:
            msg = f"a skill is named in kebab-case, got {wrong}"
            raise ValueError(msg)
        return value

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not SEMVER_PATTERN.match(value):
            msg = f"version must be semver (1.2.3), got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        if value != "internal" and not VENDOR_ORIGIN_PATTERN.match(value):
            msg = f"origin must be 'internal' or 'vendor:<owner>/<repo>', got {value!r}"
            raise ValueError(msg)
        return value

    @property
    def is_vendor(self) -> bool:
        """Vendor skills are reviewed line by line before being activated."""
        return self.origin.startswith("vendor:")


class Agent(BaseModel):
    """A loaded agent: its validated header, its body, and where it came from."""

    model_config = ConfigDict(frozen=True)

    front_matter: AgentFrontMatter
    body: str
    path: str


# ── the catalogue, over HTTP (LEKA-393) ─────────────────────────────────────


class CapabilityReason(BaseModel):
    """Why it cannot be used — or, a note, what to know: deprecated."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(
        description="refused, lifecycle, disabled, missing_source, no_model, not_permitted · "
        "deprecated"
    )
    detail: dict[str, JsonValue] = Field(default_factory=dict)


class CapabilityInputRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    type: str
    required: bool
    description: str
    choices: list[str]
    entity_types: list[str]


class CapabilitySourceNeed(BaseModel):
    """A source it needs: one of these, connected or not here."""

    model_config = ConfigDict(frozen=True)

    any_of: list[str]
    connected: bool


class CapabilityUsageRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    runs: int = Field(description="This week")
    previous: int = Field(description="The week before")
    failures: int
    average_ms: int | None


class CapabilityModelRead(BaseModel):
    """The model that would run a capability here, chosen by what it needs
    (LEKA-394)."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    title: str
    owner: Literal["leka", "workspace"]


class CapabilityModelNeeds(BaseModel):
    model_config = ConfigDict(frozen=True)

    structured: bool
    tools: bool
    context: int
    quality: int


class CapabilityRead(BaseModel):
    """One capability, for this workspace and this person. An agent's
    instructions are never sent."""

    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    summary: str = Field(description="When to use it")
    category: str
    kind: Literal["rules", "model", "agent", "workflow"]
    version: str
    lifecycle: Literal["draft", "review", "active", "deprecated", "retired"]
    origin: str
    mode: str
    risk: str
    permission: str
    inputs: list[CapabilityInputRead]
    output: str
    formats: list[str] = Field(description="What it delivers: json, pptx, pdf…")
    sources: list[CapabilitySourceNeed]
    model: bool = Field(description="Run by a model: written by one, or an agent")
    model_needs: CapabilityModelNeeds | None = Field(
        description="What that model must be able to do; none when no model runs it."
    )
    answering: CapabilityModelRead | None = Field(
        description="The model that would run it here; none when none can."
    )
    goals: list[str]
    kinds: list[str]
    entity_types: list[str]
    examples: list[str]
    always: bool
    available: bool
    reasons: list[CapabilityReason]
    notes: list[CapabilityReason]
    enabled: bool
    enabled_reason: str | None
    enabled_changed_at: datetime | None
    favourite: bool
    registered_at: datetime | None
    lifecycle_changed_at: datetime | None
    versions: int
    refused: str | None
    usage: CapabilityUsageRead


class CapabilityVersionRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    version: str
    lifecycle: str
    fingerprint: str
    registered_at: datetime
    lifecycle_changed_at: datetime
    superseded_at: datetime | None


class CapabilityEventRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    version: str
    kind: str
    from_lifecycle: str | None
    to_lifecycle: str | None
    at: datetime
    detail: dict[str, JsonValue]


class CapabilityDayUse(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: str
    runs: dict[str, int] = Field(description="By category")


class CapabilityDetail(CapabilityRead):
    """One capability, its history, its week."""

    history: list[CapabilityVersionRead]
    events: list[CapabilityEventRead]
    days: list[CapabilityDayUse]


class CategoryCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str
    count: int
    available: int


class CapabilityTop(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    category: str
    runs: int
    previous: int


class CapabilityLatest(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    summary: str
    category: str
    registered_at: datetime


class CatalogueSummary(BaseModel):
    """The catalogue at a glance (mockup 13), from what is registered and
    what the workspace's analyses ran."""

    model_config = ConfigDict(frozen=True)

    total: int
    available: int
    added_this_month: int
    categories: list[CategoryCount]
    runs: int = Field(description="This week")
    runs_previous: int
    analysis_ms: int | None = Field(description="An analysis this week, on average")
    analysis_previous_ms: int | None
    days: list[CapabilityDayUse]
    top: list[CapabilityTop]
    latest: list[CapabilityLatest]


class CapabilitySettingUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool
    reason: str | None = Field(default=None, max_length=1000, description="Required to turn off")


class CapabilityDiscovery(BaseModel):
    """What a router knows of what is asked (LEKA-398)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str | None = Field(default=None, max_length=50)
    kind: str | None = Field(default=None, max_length=50)
    entity_types: list[str] = Field(default_factory=list, max_length=20)
    text: str | None = Field(default=None, max_length=2000)
    categories: list[str] = Field(default_factory=list, max_length=20)
    available_only: bool = False


class CapabilityMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability: CapabilityRead
    score: float
    reasons: list[str] = Field(description="goal, kind, entity:<type>, words, always")


# ── language models (LEKA-394) ───────────────────────────────────────────────


class ModelPriceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    since: str = Field(description="The day this price applies from (ISO).")
    per_million_in: float
    per_million_out: float


class ModelProfileRead(BaseModel):
    """A model LEKA knows: what it takes, what it can do, what it costs."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    title: str
    context: int
    output: int
    structured: bool
    tools: bool
    quality: int = Field(description="1 enough to classify · 2 good analysis · 3 the best")
    speed: int = Field(description="1 slow · 3 fast")
    price: ModelPriceRead | None = Field(description="Today's list price; none: not published.")
    next_price: ModelPriceRead | None = Field(description="A published change to come.")
    known: bool = Field(description="False: a model the table does not know, assumed.")


class ModelProviderRead(BaseModel):
    """A provider a workspace may bring its own model from."""

    model_config = ConfigDict(frozen=True)

    name: str
    title: str
    needs: list[str] = Field(description="What it takes: key, url, model.")
    default_model: str | None
    leka_holds: bool = Field(description="LEKA holds a key for it.")
    models: list[ModelProfileRead]


class WorkspaceModelRead(BaseModel):
    """The workspace's own model — its key never shown, its last four
    characters are."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str | None
    base_url: str | None
    api_version: str | None
    key_hint: str | None
    enabled: bool
    exclusive: bool = Field(description="This model only, never LEKA's.")
    status: Literal["untested", "ok", "failed"]
    status_detail: str | None
    tested_at: datetime | None
    changed_at: datetime


class ModelRouteRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    title: str
    owner: Literal["leka", "workspace"]
    why: Literal["own", "default", "fallback", "alternative"]


class ModelGatewayRead(BaseModel):
    """What answers in this workspace, and what it could bring."""

    model_config = ConfigDict(frozen=True)

    default: ModelProfileRead
    default_ready: bool = Field(description="LEKA holds a key for its default model.")
    fallbacks: list[ModelProfileRead]
    providers: list[ModelProviderRead]
    own: WorkspaceModelRead | None
    answering: list[ModelRouteRead] = Field(description="Who would answer now, in order.")
    ready: bool = Field(description="A model can answer here.")


class WorkspaceModelUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["google", "mistral", "openai", "azure_openai", "anthropic"]
    model: str | None = Field(default=None, max_length=120)
    base_url: PublicHttpsUrl | None = None
    api_version: str | None = Field(default=None, max_length=30, pattern=r"^[0-9A-Za-z.\-]+$")
    api_key: SecretStr | None = Field(default=None, description="Kept when left out.")
    enabled: bool = True
    exclusive: bool = False


class ModelTestRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    detail: str | None
    latency_ms: int | None
    model: str | None
    version: str | None


class ModelTallyRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    calls: int
    failed: int
    tokens_in: int
    tokens_out: int
    tokens_cached: int = Field(
        default=0, description="Of tokens_in, those read from the provider's cache: billed less."
    )
    cost_usd: float
    unpriced: int = Field(description="Calls to a model without a published price.")
    average_latency_ms: int


class ModelDayRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: str
    calls: int
    failed: int
    tokens: int
    cost_usd: float


class ModelBreakdownRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    title: str
    tally: ModelTallyRead


class ModelPurposeRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    purpose: str
    tally: ModelTallyRead


class ModelCallRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    at: datetime
    purpose: str
    ref: str | None
    provider: str
    model: str
    version: str | None
    owner: str
    route: str
    attempt: int
    status: Literal["ok", "failed", "invalid"]
    error: str | None
    tokens_in: int
    tokens_out: int
    tokens_cached: int = 0
    cost_usd: float | None
    latency_ms: int
    # Whom it was asked for (LEKA-406); none: LEKA's own work.
    user_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None


class LLMRunRead(BaseModel):
    """One piece of work a model did for LEKA (LEKA-429), and how it ended."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    purpose: str
    ref: str | None
    status: Literal["succeeded", "invalid", "no_model", "timed_out", "failed"]
    provider: str | None
    model: str | None
    version: str | None
    calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: float | None
    latency_ms: int
    context_items: int
    error: str | None
    started_at: datetime


class ModelUsageRead(BaseModel):
    """What this workspace asked of models: LEKA's and its own apart."""

    model_config = ConfigDict(frozen=True)

    days: int
    total: ModelTallyRead
    previous: ModelTallyRead
    leka: ModelTallyRead
    own: ModelTallyRead
    fallbacks: int = Field(description="Answers that came from another model than the first.")
    by_day: list[ModelDayRead]
    by_model: list[ModelBreakdownRead]
    by_purpose: list[ModelPurposeRead]
    latest: list[ModelCallRead]
    runs: dict[str, int] = Field(
        description="The work models did (LEKA-429), by how it ended: succeeded, invalid, "
        "no_model, timed_out, failed."
    )
    latest_runs: list[LLMRunRead]
    intentions: int = Field(
        default=0, description="The intentions of the period a model worked for."
    )
    per_intention_usd: float | None = Field(
        default=None,
        description="What one of them cost, on average: every call made for it, "
        "understanding and answer, at list price.",
    )


# ── agent runs (LEKA-395) ───────────────────────────────────────────────────

RunStatusWord = Literal[
    "awaiting_approval", "queued", "running", "succeeded", "failed", "cancelled"
]


class AgentRunCreate(BaseModel):
    """An agent to run, with what its contract takes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1, max_length=100, description="The agent's key.")
    inputs: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, description="What its contract takes, by name."
    )
    intention_id: uuid.UUID | None = Field(
        default=None,
        description="The intention it works for: its context is the agent's (LEKA-387).",
    )
    context_id: uuid.UUID | None = Field(
        default=None,
        description="A context to read; none: assembled from what it is given.",
    )


class AgentRunDecision(BaseModel):
    """A held run approved or rejected (LEKA-406) — why, if said."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    note: str | None = Field(default=None, max_length=500)


class DeliverableRead(BaseModel):
    """A file a run delivered: GET /agent-runs/{id}/deliverables/{format}."""

    model_config = ConfigDict(frozen=True)

    format: Literal["pptx", "pdf"]
    name: str = Field(description="Its file name.")
    size: int = Field(description="In bytes.")
    slides: int


class AgentRunRead(BaseModel):
    """One run of an agent: where it stands, what it delivers, or why not."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    title: str | None = Field(description="The agent's, as the catalogue holds it now.")
    version: str = Field(description="The version that ran — or will.")
    status: RunStatusWord
    inputs: dict[str, object]
    requested_by: uuid.UUID | None
    mine: bool = Field(description="Asked by whoever reads it.")
    intention_id: uuid.UUID | None
    context_id: uuid.UUID | None
    context_version: int | None
    format: Literal["markdown", "json"] = Field(description="What it delivers.")
    pending: list[str] = Field(
        description="What it declares (pptx, pdf…) and the runtime does not render yet."
    )
    deliverables: list[DeliverableRead] = Field(
        description="The files LEKA drew of what it delivered (its pptx, its pdf), each to "
        "download.",
    )
    error: str | None = Field(
        description="Why it failed: unavailable, not_permitted, no_model, tool_rounds, timeout, "
        "invalid_output, abandoned, error."
    )
    reasons: list[dict[str, object]] = Field(
        description="When it could no longer run: the catalogue's reasons, as it said them."
    )
    provider: str | None
    model: str | None
    model_version: str | None
    tool_calls: int
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AgentRunEventRead(BaseModel):
    """One step of a run."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    seq: int
    kind: str = Field(
        description="queued, started, context, tool_withheld, tool, answered, succeeded, "
        "failed, cancelled"
    )
    at: datetime
    detail: dict[str, object]


class AgentRunUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    calls: int = Field(description="Calls to a model, every attempt.")
    tokens_in: int
    tokens_out: int
    cost_usd: float | None = Field(description="At list price; none when a price is not known.")


class AgentRunDetail(AgentRunRead):
    """A run, with what it delivered and every step."""

    output: str | None
    events: list[AgentRunEventRead]
    usage: AgentRunUsage


# ── routing (LEKA-398) ──────────────────────────────────────────────────────


class RoutingSignalRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(
        description="goal, kind, entity, words, context_types, context_sources, mode, deprecated"
    )
    points: float
    detail: str | None


class RoutedCandidateRead(BaseModel):
    """A capability the router considered: its score, the signals behind it,
    whether it can be used here — and why not."""

    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    kind: Literal["rules", "model", "agent", "workflow"]
    category: str
    score: float
    eligible: bool = Field(description="Scores enough on what is asked to be routed to.")
    selected: bool
    available: bool
    reasons: list[dict[str, object]] = Field(description="Why it cannot be used here.")
    signals: list[RoutingSignalRead]
    needs_inputs: list[str] = Field(description="An agent's inputs to ask before it runs.")


class RoutingRead(BaseModel):
    """Where an intention was routed, and why."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    subject_type: Literal["intention", "request"]
    subject_id: uuid.UUID | None
    version: int
    outcome: Literal["routed", "fallback", "clarify"]
    selected: list[str]
    candidates: list[RoutedCandidateRead] = Field(description="Ranked, usable here.")
    excluded: list[RoutedCandidateRead] = Field(
        description="Matched, but not usable here, not by this person, or against a policy "
        "(`policy`): never routed to."
    )
    background: list[str] = Field(description="Run with every analysis: not routed to.")
    fallback: str | None = Field(description="analysis: LEKA's own, when nothing fits.")
    why: str | None = Field(description="Fallback: no_match, excluded · clarify: unclear, no_goal.")
    questions: list[str] = Field(description="What to ask, to clarify.")
    suggestions: list[str] = Field(description="What it could mean, to clarify: capability keys.")
    query: dict[str, object] = Field(description="What the router read of it.")
    at: datetime


class RouteAsk(BaseModel):
    """Words to route, without an intention — what the catalogue answers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=3, max_length=2000)
    goal: str | None = Field(default=None, max_length=40)
    kind: str | None = Field(default=None, max_length=40)
    mode: Literal["question", "request"] = "question"
    entity_types: list[str] = Field(default_factory=list, max_length=20)


# ── workflows (LEKA-397) ────────────────────────────────────────────────────

WorkflowRunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
WorkflowStepStatus = Literal["pending", "running", "succeeded", "failed", "skipped", "not_reached"]


class WorkflowStepRead(BaseModel):
    """One step of a workflow, as defined."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str | None
    uses: str = Field(description="The capability it runs.")
    uses_title: str | None
    uses_kind: str | None
    after: list[str]
    when: dict[str, object] | None = Field(description="Its condition, structured; none: always.")
    given: dict[str, object] = Field(description="What it is given: {input: …} or {value: …}.")
    attempts: int
    on_failure: Literal["stop", "continue"]


class WorkflowRead(BaseModel):
    """A workflow — its steps in order, whether it can run here and why
    not. Its versions and history: GET /capabilities/{key}."""

    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    summary: str
    category: str
    version: str
    lifecycle: str
    inputs: list[CapabilityInputRead]
    steps: list[WorkflowStepRead]
    available: bool
    reasons: list[CapabilityReason]
    notes: list[CapabilityReason]


class WorkflowRunCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    inputs: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    intention_id: uuid.UUID | None = Field(
        default=None, description="The intention it works on: LEKA's own steps read its context."
    )


class WorkflowRunStepRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    step: str
    position: int
    uses: str
    status: WorkflowStepStatus
    attempts: int
    reason: str | None = Field(
        description="skipped: condition_false · not_reached: stopped, cancelled, abandoned · "
        "failed: its error."
    )
    output: dict[str, object] = Field(description="What it found: codes, summary, ref.")
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowRunEventRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    seq: int
    kind: str
    step: str | None
    at: datetime
    detail: dict[str, object]


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    title: str | None
    version: str
    status: WorkflowRunStatus
    inputs: dict[str, object]
    requested_by: uuid.UUID | None
    mine: bool
    intention_id: uuid.UUID | None
    error: str | None = Field(
        description="step_failed (failed_step says which), not_permitted, abandoned, or an error."
    )
    failed_step: str | None
    retries: int
    retryable: bool = Field(description="Failed, and trying again may mend it.")
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowRunDetail(WorkflowRunRead):
    steps: list[WorkflowRunStepRead]
    events: list[WorkflowRunEventRead]


# ── skills (LEKA-396) ────────────────────────────────────────────────────────


class SkillVersionRead(BaseModel):
    """One version of a skill: where it stands, what its contract is."""

    model_config = ConfigDict(frozen=True)

    version: str
    lifecycle: str
    fingerprint: str = Field(description="Its contract and promise, hashed.")


class SkillRead(BaseModel):
    """A skill, as a caller gets it: what it does, what it takes and gives,
    who may run it, where it stands — and every version of it."""

    model_config = ConfigDict(frozen=True)

    key: str
    version: str
    title: str
    summary: str = Field(description="What it does, when to use it.")
    category: str
    effect: str = Field(description="read: a skill never changes anything.")
    permission: str
    usable: bool = Field(description="This person may run it, and it runs.")
    lifecycle: str
    timeout: float
    origin: str
    limitations: list[str]
    reads: list[str] = Field(description="The kinds of things it reads; none: anything.")
    sources: list[list[str]] = Field(
        description="What must be connected: one source kind of each group."
    )
    missing_sources: list[list[str]] = Field(
        description="The groups of which nothing is connected here."
    )
    fingerprint: str
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    versions: list[SkillVersionRead]


class SkillRunCreate(BaseModel):
    """What a skill is run with."""

    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    version: str | None = Field(
        default=None,
        max_length=20,
        pattern=r"^\d+(\.\d+){0,2}$",
        description="1.2.0, or 1, 1.2 — the latest of them. None: the latest that runs.",
    )


class SkillRunError(BaseModel):
    field: str
    code: str
    message: str


class SkillRunRead(BaseModel):
    """One run of a skill: which, called by what about what, for whom,
    given what — what it gave, or why not."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    version: str | None
    status: Literal["succeeded", "refused", "failed", "timed_out"]
    reason: str | None
    message: str | None
    errors: list[SkillRunError]
    caller: str
    ref: str | None
    run_by: uuid.UUID | None
    mine: bool
    inputs: dict[str, JsonValue]
    output: dict[str, JsonValue] | None = Field(
        description="What it gave — none when refused, failed, or too large to keep."
    )
    cited: int = Field(description="How many things it read, citable.")
    deprecated: bool
    latency_ms: int
    at: datetime


# ── code changes (the code-change agent) ────────────────────────────────────


class CodeChangeFileRead(BaseModel):
    """One file of a proposed change: what happens to it, its diff."""

    model_config = ConfigDict(frozen=True)

    path: str
    status: Literal["added", "modified", "deleted"]
    additions: int
    deletions: int
    diff: str = Field(description="Unified diff against the branch it was read from.")
    why: str


class CodeChangeRead(BaseModel):
    """A code change an agent proposed: its files and their diffs, where it
    stands — proposed, rejected, applied as a pull request — and whether its
    source lets LEKA open that pull request."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    run_id: uuid.UUID | None
    intention_id: uuid.UUID | None
    repository: str
    base_branch: str
    title: str
    summary: str
    status: Literal["proposed", "rejected", "applied", "failed"]
    files: list[CodeChangeFileRead]
    pull_requests_allowed: bool = Field(
        description="Its GitHub source allows LEKA to open pull requests (its admin's choice)."
    )
    proposed_by: uuid.UUID | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    note: str | None
    branch: str | None
    pull_request_number: int | None
    pull_request_url: str | None
    error: str | None = Field(
        description="Why its pull request could not be opened: pull_requests_off, not_allowed, "
        "branch_exists, out_of_scope, not_found, too_large, unavailable, no_source."
    )
    error_detail: str | None
    created_at: datetime


class CodeChangeDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    note: str | None = Field(default=None, max_length=2000)
