"""What extraction hands to parsing — the contract of LEKA-354.

One stored record in, one result out: an ExtractedRecord, or an
ExtractionFailure that says why not. Never an exception: a record that
cannot be extracted is data about that record, and the next one is read.

An ExtractedRecord keeps the vendor's meaning but not its shape. A GitHub
pull request, a GitLab merge request and a Bitbucket pull request come out
with the same fields — title, content, state, people, links — each still
saying where it came from. Deciding that two of them are the same thing is
not extraction's job (parsing, LEKA-355; normalisation, LEKA-356).

Contract in docs/extraction.md.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from leka.connectors import Capability, SourceKind

# A text longer than this is cut, and says so: a README or a page can be
# megabytes, and what comes after the first hundred thousand characters is
# rarely what an answer needs. The whole payload stays in the store.
MAX_TEXT = 100_000

Scalar = str | int | float | bool | None


class Provenance(BaseModel):
    """Where an extracted record came from — enough to find the bytes again."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    source_kind: SourceKind
    capability: Capability
    external_id: str = Field(description="The vendor's id, as the index knows it.")
    container: str | None
    fetched_at: datetime
    checksum: str = Field(description="sha256 of the payload read: source_records.checksum.")
    payload_key: str | None = Field(default=None, description="The stored batch it was read from.")


class Content(BaseModel):
    """A piece of human-written text: a description, a message, a comment."""

    model_config = ConfigDict(frozen=True)

    role: str = Field(description="description, message, body, comment, …")
    format: Literal["text", "markdown"]
    text: str
    truncated: bool = False


class Reference(BaseModel):
    """Something else the record names: a person, a repository, a branch.

    In the vendor's terms — a login, an account id, a project key. Which
    entity it is, is decided later: two references with the same `email` on
    GitHub and GitLab may be one person, or not.
    """

    model_config = ConfigDict(frozen=True)

    role: str = Field(description="author, assignee, repository, parent, …")
    kind: str = Field(description="person, repository, project, issue, branch, commit, …")
    external_id: str | None = None
    name: str | None = None
    email: str | None = None


class Extracted(BaseModel):
    """What a strategy finds in one payload. The engine adds where it came from."""

    model_config = ConfigDict(frozen=True)

    title: str | None = None
    url: str | None = None
    state: str | None = Field(default=None, description="open, merged, running, … lower-cased.")
    created_at: datetime | None = None
    updated_at: datetime | None = None
    content: list[Content] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    metadata: dict[str, Scalar | list[str]] = Field(
        default_factory=dict, description="What describes it: number, labels, visibility, …"
    )
    signals: dict[str, Scalar | list[str]] = Field(
        default_factory=dict, description="Technical facts: language, region, runtime, tags, …"
    )

    @field_validator("metadata", "signals")
    @classmethod
    def _only_what_is_known(
        cls, value: dict[str, Scalar | list[str]]
    ) -> dict[str, Scalar | list[str]]:
        """A vendor that does not say is not a fact: no None, no empty list."""
        return {k: v for k, v in value.items() if v is not None and v != []}


class ExtractedRecord(Extracted):
    """One vendor object, extracted."""

    status: Literal["extracted"] = "extracted"
    provenance: Provenance
    extractor: str = Field(description="Which strategy: github.commits, aws.resources, …")
    extractor_version: int = Field(ge=1)


class FailureCode(enum.StrEnum):
    UNSUPPORTED = "unsupported"  # no strategy for this kind of record, yet
    MALFORMED = "malformed"  # the payload is not the shape the strategy knows


class ExtractionFailure(BaseModel):
    """Why one record was not extracted. Its neighbours were."""

    model_config = ConfigDict(frozen=True)

    status: Literal["failed"] = "failed"
    provenance: Provenance
    extractor: str | None
    extractor_version: int | None
    code: FailureCode
    message: str = Field(description="What was wrong — a field's name, never its value.")


Extraction = ExtractedRecord | ExtractionFailure
