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

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

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

    @field_validator("name")
    @classmethod
    def _kebab_case(cls, value: str) -> str:
        if not NAME_PATTERN.match(value):
            msg = f"name must be kebab-case, got {value!r}"
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


class CapabilityRead(BaseModel):
    """One capability, for this workspace and this person. An agent's
    instructions are never sent."""

    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    summary: str = Field(description="When to use it")
    category: str
    kind: Literal["rules", "agent"]
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
    model: bool = Field(description="Run by a model (an agent)")
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
