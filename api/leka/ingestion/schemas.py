"""Types ingestion exposes.

The pipeline is collect -> extract -> parse -> normalise. What comes out is a
NormalisedEntity: still a candidate, not yet a row. leka.knowledge decides
whether it becomes one.

`type` is a plain string here, not knowledge's EntityType enum, and that is
the dependency rule doing its job rather than an oversight. Dependencies run
knowledge -> ingestion; importing the enum would point them the other way.
The graph's vocabulary belongs to leka.knowledge, which maps these strings
and rejects the ones it does not recognise. Ingestion normalises shapes; it
does not decide what a thing *is*.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NormalisedEntity(BaseModel):
    """A candidate entity, ready for the graph but not yet in it (LEKA-356).

    `key` is its CANONICAL identifier — the same for the same thing whatever
    source names it: `github.com/acme/api#41`, `acme.atlassian.net/PAY-42`,
    `person:email:sara@acme.io`, an ARN. `external_id` is the vendor's own
    id when the entity is the record itself, else the key. `aliases` are its
    other canonical identifiers (a person's login beside their email): what
    entity resolution (LEKA-357) matches on. Rules: docs/normalisation.md.
    """

    model_config = ConfigDict(frozen=True)

    type: str
    key: str
    external_id: str
    source_id: uuid.UUID
    name: str
    attributes: dict[str, object] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    observed_at: datetime


class NormalisedRelationship(BaseModel):
    """A candidate edge, between canonical keys.

    Ingestion does not know internal ids: it has not written the entities
    yet. Resolving keys to rows is leka.knowledge's job — and a key may name
    something no source has shown yet (a ticket in another tool).
    """

    model_config = ConfigDict(frozen=True)

    type: str
    from_key: str
    to_key: str
    source_id: uuid.UUID
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: str | None = Field(default=None, description="The field it was read in.")


# ── The sync, over the API (LEKA-352) ────────────────────────────────────────


class SourceSyncRead(BaseModel):
    """Where one capability of one source stands."""

    capability: str
    status: str = Field(description="idle, running or failed.")
    since: datetime | None = Field(
        description="When the last successful pass started: where the next one reads from."
    )
    last_started_at: datetime | None
    last_succeeded_at: datetime | None
    last_full_at: datetime | None = Field(description="The last pass that read everything.")
    records_last_run: int
    records_total: int
    consecutive_failures: int
    last_error: dict[str, object] | None = Field(
        description="The last diagnostic, cleaned of secrets. Null once a pass succeeds."
    )


class SyncSummary(BaseModel):
    """One source's sync, in a line: what a list shows."""

    source_id: uuid.UUID
    records_total: int
    last_succeeded_at: datetime | None
    pass_state: str | None = Field(
        default=None,
        description="running (a worker is reading it), queued (waiting), or null.",
    )


class SourceSyncs(BaseModel):
    """A source's sync: whether a pass is under way, and each capability."""

    pass_state: str | None = Field(
        description="running (a worker is reading it), queued (waiting), or null."
    )
    capabilities: list[SourceSyncRead]


class SyncRequested(BaseModel):
    queued: bool = Field(
        description="False when a pass is already queued or running for this source: "
        "it is already happening."
    )


class SyncRunRead(BaseModel):
    """One pass over a source: what started it, how far it got, how it ended."""

    id: uuid.UUID
    trigger: str = Field(description="activation, schedule or manual.")
    full_read: bool = Field(
        description="Read at least one capability whole, ignoring where the last pass stopped."
    )
    status: str = Field(description="running, succeeded, failed or abandoned.")
    started_at: datetime
    finished_at: datetime | None
    capability: str | None = Field(description="What it is reading now, while it runs.")
    records: int
    payloads: int
    bytes: int
    error: dict[str, object] | None = Field(description="The diagnostic it ended on.")


# ── The extraction, over the API (LEKA-354) ──────────────────────────────────


class ExtractionFailureRead(BaseModel):
    """One record extraction could not make sense of."""

    capability: str
    external_id: str
    extractor: str | None = Field(description="Null: no strategy for this kind of record yet.")
    code: str = Field(description="unsupported or malformed.")
    message: str = Field(description="Names a field; never quotes the payload.")
    extracted_at: datetime


class ExtractorCount(BaseModel):
    extractor: str | None
    extracted: int
    failed: int


class SourceExtraction(BaseModel):
    """Where a source's extraction stands."""

    extracted: int
    failed: int
    unsupported: int = Field(description="Of the failed: no strategy yet.")
    malformed: int = Field(description="Of the failed: not the shape the strategy knows.")
    last_extracted_at: datetime | None
    extractors: list[ExtractorCount]
    failures: list[ExtractionFailureRead] = Field(description="The latest, newest first.")


# ── The parsing, over the API (LEKA-355) ─────────────────────────────────────


class ParseFailureRead(BaseModel):
    capability: str
    external_id: str
    code: str
    message: str = Field(description="Names a field; never quotes the record.")
    parsed_at: datetime


class SourceParsing(BaseModel):
    """Where a source's parsing stands."""

    parsed: int
    failed: int
    facts: dict[str, int] = Field(description="How many facts of each type its records gave.")
    average_quality: float | None = Field(description="0 to 1; null before anything is parsed.")
    last_parsed_at: datetime | None
    failures: list[ParseFailureRead] = Field(description="The latest, newest first.")
