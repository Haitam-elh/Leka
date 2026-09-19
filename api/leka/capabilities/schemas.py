"""The contract an agent file must satisfy.

An agent is a markdown file with YAML front matter (see
docs/adr/004-agents-as-markdown.md). There is no compiler between a typo and
production, so this model is what stands in its place: it is strict on
purpose, and it refuses rather than guesses.
"""

from __future__ import annotations

import enum
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
