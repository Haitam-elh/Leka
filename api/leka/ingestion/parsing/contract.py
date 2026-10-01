"""What parsing hands to normalisation — the contract of LEKA-355.

One ExtractedRecord in, a ParsedRecord or a ParseFailure out; never an
exception. Parsing reads what the extraction left as text and metadata and
says what it MEANS, as facts: this pull request closes PAY-42, this commit
is a fix to `billing`, this instance runs in production for the payments
team and is reachable from the internet.

Every fact says how sure it is (`confidence`) and where it was read
(`evidence`): "Fixes #41" in a body is near certain; "prod" in an instance's
name is a guess. Normalisation (LEKA-356) decides what the facts add up to.

Contract in docs/parsing.md.
"""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from leka.ingestion.extraction import Provenance

# What an excerpt may carry of the text a fact was read in: enough for a
# person to see why, not a copy of the ticket.
MAX_EXCERPT = 120


class FactType(enum.StrEnum):
    REFERENCES = "references"  # another work item, commit or page: value is how (closes, mentions)
    MENTIONS = "mentions"  # a person, by handle
    LINKS_TO = "links_to"  # a URL nothing more is known of: value is its host
    CHANGE_TYPE = "change_type"  # feat, fix, chore… (Conventional Commits)
    SCOPE = "scope"  # what a change touches: feat(billing)
    BREAKING = "breaking"  # a change that breaks its users
    CATEGORY = "category"  # bug, feature, incident, security, docs, task, epic, maintenance
    ENVIRONMENT = "environment"  # production, staging, development, test
    SERVICE = "service"  # the service a resource belongs to
    APPLICATION = "application"  # the application — a group of services — it belongs to
    OWNER = "owner"  # the team or person responsible
    EXPOSURE = "exposure"  # public, internal
    CRITICALITY = "criticality"  # critical, high, medium, low
    CLUSTER = "cluster"  # the Kubernetes cluster a machine is a node of
    # What a column holds — contact, identity, location, financial,
    # credential, health, personal — its target the column (LEKA-364).
    DATA_CATEGORY = "data_category"
    # How a table's own documentation classifies it: confidential, restricted.
    CLASSIFICATION = "classification"


class Target(BaseModel):
    """What a fact points at, in the terms it was written in."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(description="issue, pull_request, commit, person, url, …")
    key: str = Field(description="PAY-42, acme/api#41, #41, a sha, a handle, a URL.")
    system: str | None = Field(default=None, description="jira, github, gitlab, … when known.")


class Evidence(BaseModel):
    """Where a fact was read."""

    model_config = ConfigDict(frozen=True)

    field: str = Field(description="title, content.body, metadata.labels, signals.tags, …")
    excerpt: str | None = Field(default=None, description="The words around it, cut short.")


class Fact(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: FactType
    value: str | None = None
    target: Target | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Evidence


class TextStructure(BaseModel):
    """The shape of a record's human-written text, all contents together."""

    model_config = ConfigDict(frozen=True)

    words: int = 0
    headings: list[str] = Field(default_factory=list)
    code_languages: list[str] = Field(default_factory=list)
    code_blocks: int = 0
    tasks_total: int = 0
    tasks_done: int = 0
    links: int = 0


class Quality(BaseModel):
    """How much there was to read. 1.0: a title, text, nothing cut."""

    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list, description="What lowered it.")


class ParsedRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["parsed"] = "parsed"
    provenance: Provenance
    extractor: str
    extractor_version: int
    parser_version: int
    facts: list[Fact] = Field(default_factory=list)
    structure: TextStructure
    quality: Quality


class ParseFailureCode(enum.StrEnum):
    MALFORMED = "malformed"  # not an ExtractedRecord, or a parser choked on it


class ParseFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["failed"] = "failed"
    provenance: Provenance | None = Field(description="Null when the input was not readable.")
    parser_version: int
    code: ParseFailureCode
    message: str = Field(description="What was wrong — never a value from the record.")


Parsed = ParsedRecord | ParseFailure
