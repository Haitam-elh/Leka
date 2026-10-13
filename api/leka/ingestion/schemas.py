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
from typing import Literal

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


# ── enrichment (LEKA-359) ────────────────────────────────────────────────────


class EntityRef(BaseModel):
    """A resolved entity, named."""

    id: uuid.UUID
    type: str
    key: str
    name: str


class EnrichedAttributeRead(BaseModel):
    """An attribute enrichment added — never one the sources state."""

    attribute: str
    value: object
    confidence: float
    rule: str = Field(description="The enrichment rule that made it (docs/enrichment.md).")
    evidence: str
    inputs: list[str] = Field(description="The keys of what it was made from.")


class EnrichedRelationshipRead(BaseModel):
    """A relationship between two resolved entities, and where it comes from."""

    type: str
    origin: str = Field(description="stated: by a source; inferred: by an enrichment rule.")
    rule: str
    confidence: float
    cross_source: bool = Field(description="Its two ends are shown by different sources.")
    sources: int = Field(description="How many sources state it; 0 for an inferred one.")
    evidence: str
    provenance: list[dict[str, object]] = Field(
        description="Stated: {source_id, record_id, evidence} of the first records stating "
        "it. Inferred: {entity_id} of what it was inferred from beyond its two ends."
    )
    from_entity: EntityRef
    to_entity: EntityRef


class EnrichedEntity(ResolvedEntityRead):
    """A resolved entity as the company model reads it: what its sources
    say (`attributes`), what enrichment adds (`enriched`), and its
    relationships both ways."""

    enriched: list[EnrichedAttributeRead]
    outgoing: list[EnrichedRelationshipRead]
    outgoing_total: int
    incoming: list[EnrichedRelationshipRead]
    incoming_total: int


class EnrichmentRunRead(BaseModel):
    status: str
    started_at: datetime
    finished_at: datetime | None
    counts: dict[str, object]
    failures: list[dict[str, object]] = Field(
        description="{enricher, error}: an enricher that failed; its output was dropped."
    )
    error: str | None


class EnrichmentStatus(BaseModel):
    """Where the workspace's enrichment stands."""

    pending: bool = Field(description="Resolution made something the last run did not read.")
    last_run: EnrichmentRunRead | None
    counts: dict[str, int] = Field(
        description="relationships — stated, inferred, cross_source — and attributes."
    )
    relationships: dict[str, int] = Field(description="How many per `type:rule`.")
    attributes: dict[str, int] = Field(description="How many of each enriched attribute.")


# ── the environment screens (LEKA-359, mockups 10 and 11) ───────────────────


TwinStateName = Literal["unavailable", "degraded", "stale", "unknown", "not_covered", "operational"]


class TwinSourceRead(BaseModel):
    """A source, in the state it is in now (LEKA-442): never « lue » when
    it is failing, late or never read."""

    id: uuid.UUID
    kind: str
    name: str
    category: str = Field(description="code, project, docs, cloud, observability, data, chat.")
    state: Literal["read", "error", "degraded", "stale", "syncing", "disabled", "never"]
    last_synced_at: datetime | None
    error: str | None = Field(description="What its last check or read said, cleaned.")
    webhooks: bool = Field(description="It receives what its system sends, as it is sent.")


class TwinIncidentRead(BaseModel):
    """The open incident a state rests on: its record, how bad."""

    id: uuid.UUID
    key: str
    name: str
    severity: str | None


class TwinStateRead(BaseModel):
    """A thing's state in the Digital Twin (LEKA-442), with where it comes
    from and how fresh — « inconnu » never meaning « sain »."""

    state: TwinStateName
    basis: Literal["measured", "declared", "deduced", "none"] = Field(
        description="measured — a monitoring tool or an incident record; declared — its "
        "provider's word; deduced — from what runs it; none — nothing says."
    )
    reason: str = Field(
        description="incident_open, resource_failed, resource_paused, resource_running, "
        "monitored_quiet, deduced_health, no_monitoring_source, no_signal, sources_stale, "
        "sources_failing."
    )
    observed_at: datetime | None = Field(description="When a source last read it.")
    signal: list[str] = Field(description="The sources it rests on, by name.")
    fresh: bool = Field(description="Read by at least one source within STALE_AFTER.")
    was: TwinStateName | None = Field(description="What it was, when stale.")
    certainty: Literal["confirmed", "suspected", "unverified"]
    incident: TwinIncidentRead | None


class TwinCoverageRead(BaseModel):
    """A part of the twin, covered or not, and by which sources."""

    part: Literal[
        "applications", "services", "health", "incidents", "data", "infrastructure", "teams"
    ]
    covered: bool
    sources: list[uuid.UUID]


class TwinFreshnessRead(BaseModel):
    """When the twin was last observed, how often it is — never « temps
    réel » when it is not."""

    last_read_at: datetime | None = Field(description="The latest read of a connected source.")
    every_minutes: int = Field(description="How often sources are read.")
    late: bool = Field(description="No connected source read within twice that.")
    webhooks: bool = Field(description="A source receives what its system sends, as it is sent.")


class EnvironmentNodeRead(BaseModel):
    """A box of the map: an entity, or a provider's cloud resources together."""

    id: str
    type: str = Field(description="repository, service, database — or provider.")
    layer: str = Field(description="applications, services, data or infrastructure.")
    name: str
    status: str | None = Field(
        description="operational, attention, incident, unmonitored — none when it has no state."
    )
    entity_id: uuid.UUID | None
    key: str | None
    detail: str | None = Field(description="A provider's region.")
    count: int = Field(description="A provider's resources; 1 for an entity.")
    environment: str | None
    team: EntityRef | None
    twin: TwinStateRead | None = Field(
        default=None,
        description="Its state in the Digital Twin (LEKA-442); a provider's box: its worst.",
    )


class EnvironmentEdgeRead(BaseModel):
    from_id: str
    to_id: str
    type: str
    status: str | None = Field(description="The worse state of its two ends.")


class EnvironmentEventRead(BaseModel):
    """Something that moved: when, what it is now, and where."""

    entity: EntityRef
    at: str
    kind: str = Field(description="incident, resolved, attention, change or information.")
    where: EntityRef | None = Field(description="Its service, repository or project.")
    source_kinds: list[str]


class AttentionPointRead(BaseModel):
    """What needs someone's attention, and how much."""

    kind: str = Field(
        description="open_incident, failed_resources, stopped_resources, stale_work, "
        "unmonitored_services or dormant_repositories."
    )
    level: str = Field(description="high, medium or info.")
    count: int
    entity: EntityRef | None
    detail: str | None


class EnvironmentRead(BaseModel):
    """The workspace's environment, as mockup 10 lays it out."""

    updated_at: datetime | None = Field(description="When the last enrichment finished.")
    nodes: list[EnvironmentNodeRead]
    edges: list[EnvironmentEdgeRead]
    layers: dict[str, int] = Field(description="How many things each layer holds.")
    environments: list[str] = Field(description="The environments its things say they are in.")
    services: int = Field(description="The company's own services; the external ones apart.")
    services_operational: int = Field(description="Measured, or deduced from what runs them.")
    services_deduced: int = Field(
        default=0, description="Whose state is deduced from what runs them, no tool measuring it."
    )
    services_external: int = Field(default=0, description="Services it uses and does not run.")
    services_unknown: int = Field(
        default=0,
        description="Whose state nothing says: no tool measures it, nothing known runs it.",
    )
    incidents_open: int
    services_impacted: int
    changes_24h: int
    attention: list[AttentionPointRead]
    events: list[EnvironmentEventRead]
    states: dict[str, int] = Field(
        default_factory=dict,
        description="How many things with a state are in each (LEKA-442), every state said.",
    )
    freshness: TwinFreshnessRead | None = None
    coverage: list[TwinCoverageRead] = Field(default_factory=list)
    sources: list[TwinSourceRead] = Field(default_factory=list)


class EntityActivityEvent(EnvironmentEventRead):
    """Something that moved around a thing, with what it says of itself."""

    state: str | None = None
    url: str | None = None
    version: str | None = None
    environment: str | None = None


class EntityActivityDay(BaseModel):
    day: str
    changes: int = Field(description="Commits and pull requests")
    deployments: int = Field(description="Deployments and releases")
    incidents: int
    work: int = Field(description="Issues and tickets")
    other: int


class EntityActivityRead(BaseModel):
    """Everything that moved around one thing over a period — its
    activity, its deployments, its log (LEKA's view of it, from its
    sources), and how much, day by day."""

    days: int
    since: str
    events: list[EntityActivityEvent]
    by_day: list[EntityActivityDay]
    changes: int
    deployments: int
    incidents: int
    incidents_open: int
    work: int
    work_open: int
    last_activity: str | None
    previous: dict[str, int] = Field(
        description="The same counts over the period before: changes, deployments, incidents, work."
    )
    log_sources: list[str] = Field(
        description="The connected sources that keep logs or metrics (datadog, splunk…)."
    )
    mentions: list[EntityRef] = Field(
        description="Documents that name it, not yet linked to it as its documentation."
    )


class SheetPersonRead(BaseModel):
    entity: EntityRef
    confidence: float
    evidence: str


class SheetTeamRead(BaseModel):
    entity: EntityRef
    confidence: float
    origin: str
    members: int = Field(description="The people who work with it, as enrichment infers.")


class SheetLinkRead(BaseModel):
    """A thing related to this one, and how."""

    entity: EntityRef
    type: str
    direction: str = Field(description="out: this one → it; in: it → this one.")
    status: str | None
    origin: str
    confidence: float
    cross_source: bool


class EntitySheetRead(BaseModel):
    """One entity, as mockup 11 lays it out."""

    entity: EnrichedEntity
    status: str | None
    deduced: bool = Field(
        default=False, description="Its state is deduced from what runs it, no tool measuring it."
    )
    twin: TwinStateRead | None = Field(
        default=None, description="Its state, where it comes from, how fresh (LEKA-442)."
    )
    sources: list[TwinSourceRead] = Field(
        default_factory=list, description="The sources that show it, each in its state."
    )
    environment: str | None
    owner: SheetPersonRead | None
    team: SheetTeamRead | None
    incidents: list[EnvironmentEventRead]
    events: list[EnvironmentEventRead]
    dependencies: list[SheetLinkRead]
    documents: list[EntityRef]
    attention: list[AttentionPointRead]
    source_kinds: list[str]
