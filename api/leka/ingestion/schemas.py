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
    trigger: str = Field(description="activation, schedule, manual, settings or webhook.")
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


class WebhookDeliveryRead(BaseModel):
    """One delivery a webhook source received, signed (LEKA-350) — never its body."""

    id: uuid.UUID
    received_at: datetime
    status: str = Field(description="pending, stored, ignored or rejected.")
    delivery_id: str | None = Field(description="The sender's own id for it, when it gives one.")
    size_bytes: int
    resource: str | None = Field(description="The resource it was.")
    records: int = Field(description="Records it held, to store.")
    gone: int = Field(description="Records it said were deleted.")
    error: dict[str, object] | None = Field(description="Why it was rejected: {reason, message}.")
    processed_at: datetime | None


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


# ── The normalisation, over the API (LEKA-356) ───────────────────────────────


class NormalisationFailureRead(BaseModel):
    capability: str
    external_id: str
    code: str = Field(description="unsupported, invalid or malformed.")
    message: str = Field(description="Names what is missing; never quotes the record.")
    normalised_at: datetime


class SourceNormalisation(BaseModel):
    """Where a source's normalisation stands."""

    normalised: int
    failed: int
    unsupported: int
    invalid: int
    malformed: int
    entities: dict[str, int] = Field(description="The records' own entities, by type.")
    relationships: dict[str, int] = Field(description="Their relationships, by type.")
    with_diagnostics: int = Field(description="Normalised, with something kept as the vendor said.")
    last_normalised_at: datetime | None
    failures: list[NormalisationFailureRead] = Field(description="The latest, newest first.")


# ── Validation, over the API (LEKA-358) ──────────────────────────────────────


class QualityScores(BaseModel):
    """Means over the validated records, from 0 to 1 — none before any."""

    quality: float | None = Field(description="Over the records not quarantined.")
    completeness: float | None
    consistency: float | None
    freshness: float | None
    confidence: float | None


class ValidationIssueCount(BaseModel):
    """A kind of issue, how many records have it, and what to do about it."""

    code: str
    severity: str = Field(description="error (quarantines), warning or info.")
    records: int
    remediation: str


class QuarantinedRecordRead(BaseModel):
    """A record kept out of the company model, and why."""

    entity_type: str | None
    entity_key: str | None
    issues: list[dict[str, object]]
    validated_at: datetime


class SourceValidation(BaseModel):
    """Where a source's validation stands."""

    valid: int
    warning: int
    quarantined: int
    scores: QualityScores
    last_validated_at: datetime | None
    issues: list[ValidationIssueCount] = Field(description="The most frequent first.")
    quarantined_records: list[QuarantinedRecordRead] = Field(description="The latest first.")


class SourceQuality(BaseModel):
    """One line per source of the workspace: how its records validate."""

    source_id: uuid.UUID
    valid: int
    warning: int
    quarantined: int
    quality: float | None
    last_validated_at: datetime | None


# ── The pipeline, over the API (LEKA-360) ────────────────────────────────────


class ProcessingRunRead(BaseModel):
    """One run of one stage over a source."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stage: str
    status: str = Field(description="running, succeeded, failed or abandoned.")
    started_at: datetime
    finished_at: datetime | None
    counts: dict[str, object]
    versions: dict[str, object]
    error: str | None = Field(description="The exception's type; its details are in the logs.")


class StageState(BaseModel):
    stage: str
    job: str | None = Field(description="running (a worker has it), queued, or null.")
    pending: bool = Field(description="Whether it has rows to make or make again.")
    last_run: ProcessingRunRead | None


class SourcePipeline(BaseModel):
    """Where a source's processing stands, stage by stage, in order."""

    stages: list[StageState]
    processed_through: bool = Field(
        description="Nothing pending and nothing under way: every stage is up to date."
    )


class PipelineQueued(BaseModel):
    queued: str | None = Field(description="The stage queued, or null when none had work.")


# ── Entity resolution, over the API (LEKA-357) ───────────────────────────────


class ResolvedEntityRead(BaseModel):
    """One real thing, as the workspace's sources show it."""

    id: uuid.UUID
    type: str
    key: str = Field(description="The key that says it best; every other is in `keys`.")
    name: str
    names: list[str] = Field(description="Every name it goes by, the chosen one first.")
    attributes: dict[str, object] = Field(
        description="What its sources say it is: where they disagree, the chosen value."
    )
    conflicts: list[dict[str, object]] = Field(
        description="Where its sources disagree: {attribute, chosen, values: [{value, "
        "source_id, key, observed_at}]} — every value kept."
    )
    confidence: float = Field(description="How sure the merges that made it are.")
    quality: float | None = Field(
        description="The best quality validation gave the records that are it (LEKA-358)."
    )
    sources: int
    resolved_at: datetime


class ResolvedKeyRead(BaseModel):
    """A key it goes by, as one source gave it: the provenance."""

    key: str
    source_id: uuid.UUID
    kind: str = Field(description="key, alias or derived.")
    name: str | None
    records: int = Field(description="Records of the source that are it.")
    named: int = Field(description="Records of the source that name it.")
    first_seen_at: datetime | None
    last_seen_at: datetime | None


class ResolutionDecisionRead(BaseModel):
    """What was decided, and why."""

    kind: str = Field(description="merge, link or ambiguous.")
    rule: str
    confidence: float
    keys: list[str]
    evidence: str
    other_entity_id: uuid.UUID | None = Field(
        description="A link's other end, from this entity's side."
    )


class ResolvedEntityDetail(ResolvedEntityRead):
    keys: list[ResolvedKeyRead]
    decisions: list[ResolutionDecisionRead]


class ResolutionRunRead(BaseModel):
    status: str
    started_at: datetime
    finished_at: datetime | None
    counts: dict[str, object]
    error: str | None


class ResolutionStatus(BaseModel):
    """Where the workspace's resolution stands."""

    pending: bool = Field(description="Normalisation made something the last run did not read.")
    last_run: ResolutionRunRead | None
    counts: dict[str, int] = Field(
        description="entities, conflicted, and and decisions: merges, links, ambiguous."
    )
