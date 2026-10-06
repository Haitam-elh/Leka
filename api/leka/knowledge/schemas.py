"""Types the knowledge module exposes: the company model as it is read.

The per-type validation of `attributes` is the registry's (registry.py):
the database cannot check what is inside a JSONB column —
docs/adr/003-entity-model.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from leka.knowledge.models import EntityType, Lifecycle, RelationshipType


class EntityRead(BaseModel):
    """An entity of the company model."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    type: EntityType
    key: str = Field(description="The key that says it best (docs/resolution.md).")
    name: str
    attributes: dict[str, object]
    lifecycle: Lifecycle
    version: int = Field(description="Raised each time what it says changes.")
    schema_version: int = Field(description="Its type's schema version it was checked against.")
    confidence: float
    quality: float | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    removed_at: datetime | None


class EntityBrief(BaseModel):
    """An entity, named: the other end of a relationship."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    type: EntityType
    key: str
    name: str
    lifecycle: Lifecycle


class RelationshipRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    type: RelationshipType
    confidence: float
    origin: str = Field(
        description="stated by a source, inferred by an enrichment rule, or accepted: "
        "proposed by LEKA's enrichment and validated (LEKA-380)."
    )
    rule: str
    cross_source: bool
    attributes: dict[str, object] = Field(
        description="environments: the ones it is true in. Empty: everywhere, or unknown."
    )


class LinkRead(RelationshipRead):
    """A relationship from one entity's side: the other end, named."""

    direction: str = Field(description="out: this entity → the other; in: the other → it.")
    other: EntityBrief


class EntityDetail(EntityRead):
    """An entity, where every piece of it came from, and its relationships."""

    provenance: dict[str, object] = Field(
        description="sources: every source and key it goes by; attributes: each "
        "attribute's origin — a source, or an enrichment rule and its confidence."
    )
    relationships: list[LinkRead]
    relationships_total: int
    versions: int


class EntityVersionRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    version: int
    content: dict[str, object]
    changed: list[str]
    schema_version: int
    recorded_at: datetime


class Neighbourhood(BaseModel):
    """One entity and what surrounds it.

    The unit leka.context asks for. Returning a subgraph rather than a list
    of rows keeps traversal knowledge inside this module.
    """

    model_config = ConfigDict(frozen=True)

    root: EntityRead
    entities: list[EntityRead] = Field(default_factory=list)
    relationships: list[RelationshipRead] = Field(default_factory=list)


class MaterialSource(BaseModel):
    """A source what the material says came from: its id, kind and name —
    and how it is doing, which the context's ranking reads (LEKA-372)."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    kind: str
    name: str
    status: str | None = Field(
        default=None, description="active, degraded, error, disabled… (leka.connectors)."
    )
    health: str | None = Field(default=None, description="healthy, degraded, unhealthy, unknown.")


class MaterialEntity(BaseModel):
    """An entity as context reads it: what it is, how far from the roots,
    and where every piece of it came from — the sources and keys it goes
    by, each attribute's origin (a source, or an enrichment rule and its
    confidence and evidence)."""

    model_config = ConfigDict(frozen=True)

    entity: EntityRead
    depth: int | None = Field(
        description="Steps from the nearest root; 0 for a root; none when it was found by "
        "something else than a walk — a search, its time."
    )
    provenance: dict[str, object]


class MaterialRelationship(BaseModel):
    """A relationship as context reads it: what stated it — its records and
    their evidence — or what it was inferred from, and its life."""

    model_config = ConfigDict(frozen=True)

    relationship: RelationshipRead
    provenance: list[dict[str, object]]
    first_seen_at: datetime | None
    changed_at: datetime | None


class ContextMaterial(BaseModel):
    """What leka.context assembles from (LEKA-370): the entities around some
    roots, the relationships among them, each with its provenance, the
    sources they came from, and which build of the model they were read
    from — so that a context says what it was made of, and when."""

    model_config = ConfigDict(frozen=True)

    roots: list[uuid.UUID]
    entities: list[MaterialEntity] = Field(description="The roots first, then the nearest.")
    relationships: list[MaterialRelationship]
    sources: list[MaterialSource]
    truncated: bool = Field(description="More was reached than a walk holds.")
    built_at: datetime | None = Field(description="When the model read was built.")
    model_version: int


class ModelBuild(BaseModel):
    """A build of the model that succeeded (LEKA-374): what it recorded is
    dated when it started; what read it, when it finished."""

    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    started_at: datetime
    finished_at: datetime


class ModelChange(BaseModel):
    """One thing a build changed (LEKA-374): an entity added, changed —
    which of its fields — or removed; a relationship that appeared, changed
    or went, between its two ends."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["entity", "relationship"]
    change: Literal["added", "changed", "removed"]
    entity_id: uuid.UUID | None = Field(default=None, description="The entity.")
    from_id: uuid.UUID | None = Field(default=None, description="A relationship's ends.")
    to_id: uuid.UUID | None = None
    type: str = Field(description="The entity's type, or the relationship's.")
    name: str = Field(description="The entity's name, or the relationship's ends: A → B.")
    fields: list[str] = Field(default_factory=list, description="What of an entity changed.")
    at: datetime = Field(description="When the build recorded it.")
    run_id: uuid.UUID | None


class ModelChanges(BaseModel):
    """What some builds changed (LEKA-374), the oldest first — at most so
    many: `truncated` when there was more."""

    model_config = ConfigDict(frozen=True)

    changes: list[ModelChange]
    truncated: bool


class ModelRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    started_at: datetime
    finished_at: datetime | None
    model_version: int
    counts: dict[str, object]
    error: str | None


class ModelStatus(BaseModel):
    """Where the workspace's company model stands."""

    pending: bool = Field(description="Enrichment made something the last build did not read.")
    model_version: int
    last_run: ModelRunRead | None
    types: dict[str, int] = Field(description="Entities of each type, the removed left out.")
    lifecycles: dict[str, int]
    relationships: dict[str, int]


class EntityKindRead(BaseModel):
    """A kind of entity, as the registry defines it."""

    type: EntityType
    version: int
    category: str
    attributes: list[str] = Field(description="The attributes its schema declares.")
    built_from: list[str]


class RelationshipKindRead(BaseModel):
    """A kind of relationship and its contract (LEKA-368)."""

    type: RelationshipType
    version: int
    built_from: list[str]
    meaning: str = Field(description="Read from → to: `is part of`, `depends on`…")
    sources: list[EntityType] | None = Field(description="The kinds its start may be; None: any.")
    targets: list[EntityType] | None = Field(description="The kinds its end may be; None: any.")
    single: bool = Field(description="A thing has one: a person's manager, a ticket's parent.")
    acyclic: bool = Field(description="A loop of it is a contradiction.")
    dependency: bool = Field(description="What a thing needs to work: a dependency walk's.")


class Registry(BaseModel):
    model_version: int
    entities: list[EntityKindRead]
    relationships: list[RelationshipKindRead]


# ── the landscape: applications and services (LEKA-362) ─────────────────────


class Criticality(BaseModel):
    """How critical a service or an application is, and who says so."""

    model_config = ConfigDict(frozen=True)

    level: str = Field(description="critical, high, medium, low — or the source's own word.")
    origin: str = Field(
        description="source: a catalogue or a tag said it; enrichment: its parts show it; "
        "accepted: LEKA proposed it and it was validated (LEKA-380)."
    )
    confidence: float | None
    raw: str | None = Field(description="The source's own word: tier 1, mission-critical.")


class LandscapeRead(BaseModel):
    """A service or an application, as the landscape shows it: how critical,
    where in its life, where it runs, whose it is, what it depends on."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    type: EntityType
    key: str
    name: str
    lifecycle: Lifecycle
    stage: str | None = Field(description="experimental, production, deprecated, retired.")
    criticality: Criticality | None
    environments: list[str]
    applications: list[EntityBrief] = Field(description="What it is part of.")
    owners: list[EntityBrief] = Field(description="Its teams.")
    maintainers: list[EntityBrief]
    services: int = Field(description="An application's services.")
    dependencies: int = Field(description="What it depends on, directly.")
    dependents: int = Field(description="What depends on it, directly.")
    last_seen_at: datetime | None


class PartRead(BaseModel):
    """What a service or an application is made of: a resource, a database,
    a repository, a service — and the environments it is theirs in."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    environments: list[str]


class DependencyRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    confidence: float
    origin: str
    environments: list[str] = Field(description="Empty: everywhere, or unknown.")


class LandscapeDetail(LandscapeRead):
    """One service or application: everything above, what it is made of,
    what it depends on and what depends on it, where each piece came from."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    parts: list[PartRead]
    depends_on: list[DependencyRead]
    depended_on_by: list[DependencyRead]


class DependencyNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    depth: int = Field(description="Steps of depends_on from the root.")
    criticality: str | None


class Dependencies(BaseModel):
    """What an entity depends on, transitively — or what depends on it:
    what a failure of it reaches."""

    model_config = ConfigDict(frozen=True)

    root: EntityBrief
    direction: Literal["downstream", "upstream"]
    environment: str | None
    depth: int
    nodes: list[DependencyNode] = Field(description="Without the root, the nearest first.")
    relationships: list[RelationshipRead]
    truncated: bool = Field(description="More was reached than a response holds.")


# ── infrastructure and cloud (LEKA-363) ──────────────────────────────────────


class ResourceEnvironment(BaseModel):
    """Where a resource runs, and who says so."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="production, staging, development, test — or the source's word.")
    origin: str = Field(
        description="source: a tag, a name, a CMDB said it; enrichment: what it is in runs there."
    )
    confidence: float | None


class InfrastructureRead(BaseModel):
    """A cloud resource or a database: what kind, of which class, where —
    its provider, account, group, region — in which environment, how
    reachable and critical, whose it is, what it serves."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    type: EntityType
    key: str
    name: str
    lifecycle: Lifecycle
    provider: str | None = Field(description="aws, azure, gcp — none for a CMDB's own server.")
    resource_kind: str | None = Field(
        description="instance, function, cluster, network, load_balancer, bucket, database."
    )
    resource_class: str | None = Field(description="compute, network, storage, database.")
    resource_type: str | None = Field(description="The provider's own: ec2:instance, …")
    state: str | None = Field(
        description="running, starting, stopping, stopped, deleting, terminated, failed."
    )
    account: EntityBrief | None = Field(description="The account, subscription or project.")
    resource_group: EntityBrief | None = Field(description="An Azure resource's group.")
    region: str | None
    zone: str | None
    environment: ResourceEnvironment | None
    exposure: str | None = Field(description="public, internal.")
    criticality: Criticality | None
    services: list[EntityBrief] = Field(description="The services it is part of.")
    applications: list[EntityBrief] = Field(description="The applications it is part of.")
    owners: list[EntityBrief] = Field(description="Its teams.")
    network: EntityBrief | None = Field(description="The network it is in.")
    cluster: EntityBrief | None = Field(description="The cluster it is a node of.")
    dependencies: int = Field(description="What it depends on, directly.")
    dependents: int = Field(description="What depends on it, directly.")
    last_seen_at: datetime | None


class InfrastructureDetail(InfrastructureRead):
    """One resource: everything above, what it holds — a cluster's nodes, a
    network's resources — what it depends on and what depends on it, where
    each piece came from."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    holds: list[EntityBrief] = Field(description="What is part of it, or in it.")
    holds_total: int
    depends_on: list[DependencyRead]
    depended_on_by: list[DependencyRead]


class CloudAccountRead(BaseModel):
    """What resources are in — an AWS account, an Azure subscription or
    resource group, a Google Cloud project — and how much is in it."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    type: EntityType
    key: str
    name: str
    lifecycle: Lifecycle
    provider: str | None
    account_type: str | None = Field(
        description="aws_account, azure_subscription, gcp_project — none for a resource group."
    )
    account_id: str | None = Field(description="The provider's id: 123456789012, acme-prod.")
    state: str | None = Field(description="active, disabled, deleted.")
    organization: str | None = Field(
        description="What it is in: an AWS organisation, an Azure tenant, a folder or "
        "organisation at Google."
    )
    parent: EntityBrief | None = Field(description="A resource group's subscription.")
    environment: ResourceEnvironment | None
    criticality: Criticality | None
    owners: list[EntityBrief]
    resources: int = Field(description="The resources in it — in its groups too — not removed.")
    classes: dict[str, int] = Field(description="Of them, how many of each class.")
    regions: list[str]
    last_seen_at: datetime | None


class CloudAccountDetail(CloudAccountRead):
    """One account, subscription, project or resource group: everything
    above, its resource groups, and where each piece came from."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    resource_groups: list[CloudAccountRead]


# ── data: databases, schemas, data objects (LEKA-364) ────────────────────────


class Holds(BaseModel):
    """What data something holds: the kinds, the most sensitive
    classification, whether personal data — and who says so."""

    model_config = ConfigDict(frozen=True)

    classification: str | None = Field(
        description="restricted, confidential, internal, public — or the source's word."
    )
    data_categories: list[str] = Field(
        description="contact, identity, location, financial, credential, health, personal."
    )
    personal_data: bool
    origin: str | None = Field(
        description="source: its columns, its documentation, a catalogue said it; "
        "enrichment: what it holds does."
    )


class DatabaseRead(BaseModel):
    """A database: what a database source reads on a server — or a cloud
    instance serving databases — where it is, what it holds."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    engine: str | None = Field(
        description="postgresql, mysql, mariadb, sqlserver, oracle, mongodb."
    )
    host: str | None
    port: int | None
    database_name: str | None = Field(description="None for a server whose schemas are databases.")
    provider: str | None = Field(description="aws, azure — a cloud instance's.")
    instance: EntityBrief | None = Field(description="The cloud instance serving it.")
    schema_count: int
    object_count: int = Field(description="Its tables, views, collections — not removed.")
    holds: Holds
    environment: ResourceEnvironment | None
    owners: list[EntityBrief]
    services: list[EntityBrief]
    last_seen_at: datetime | None


class SchemaRead(BaseModel):
    """A schema — a MySQL or MongoDB database — and what is in it."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    object_count: int
    kinds: dict[str, int] = Field(description="Of them, how many tables, views, collections…")
    holds: Holds
    owners: list[EntityBrief]
    services: list[EntityBrief]


class DatabaseDetail(DatabaseRead):
    """One database: everything above, its schemas, the databases it serves
    (an instance), where each piece came from."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    schemas: list[SchemaRead] = Field(description="By name.")
    serves: list[EntityBrief] = Field(description="An instance's databases.")


class Ties(BaseModel):
    """How a data object is tied to the others, counted."""

    model_config = ConfigDict(frozen=True)

    references: int = Field(description="The tables its foreign keys point at.")
    referenced_by: int
    reads_from: int = Field(description="What a view reads.")
    read_by: int


class DataObjectRead(BaseModel):
    """A table, a view, a collection: where it is, how big, what it holds,
    how it is tied to the others."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    object_kind: str | None = Field(
        description="table, partitioned_table, view, materialized_view, foreign_table, collection."
    )
    engine: str | None
    database: EntityBrief | None
    schema_name: str | None
    container: EntityBrief | None = Field(description="Its schema.")
    column_count: int
    estimated_rows: int | None
    size_bytes: int | None
    holds: Holds
    owners: list[EntityBrief]
    services: list[EntityBrief]
    ties: Ties
    last_seen_at: datetime | None


class ColumnRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    category: str | None = Field(description="What kind of data it holds, when known.")
    primary_key: bool


class DataObjectDetail(DataObjectRead):
    """One data object: everything above, its columns, what it is tied to,
    where each piece came from."""

    description: str | None
    columns: list[ColumnRead]
    attributes: dict[str, object]
    provenance: dict[str, object]
    references: list[EntityBrief]
    referenced_by: list[EntityBrief]
    reads_from: list[EntityBrief]
    read_by: list[EntityBrief]


# ── people and teams (LEKA-365) ──────────────────────────────────────────────


class Tie(BaseModel):
    """Another entity, and how sure and whence the relationship to it: a
    source stated it, or a rule inferred it."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    origin: str = Field(description="stated, inferred, accepted.")
    rule: str = Field(description="stated, or the rule that inferred it: inherited, works_with…")
    confidence: float


class Expertise(BaseModel):
    """What a person's work shows they know, and the evidence."""

    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    type: str = Field(description="repository, project, service.")
    items: int = Field(description="How many of their items are in it.")
    roles: dict[str, int] = Field(description="authored, reviewed, assigned, led… how many each.")
    last_at: str | None


class TeamRead(BaseModel):
    """A team — or a department — its place in the organisation, its
    people, what it owns."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    team_type: str | None = Field(description="team, department.")
    parent: EntityBrief | None
    sub_team_count: int
    member_count: int = Field(description="Its members a source states.")
    inferred_member_count: int = Field(description="Those its work suggests (works_with).")
    leads: list[EntityBrief]
    owns: dict[str, int] = Field(description="What it owns, by type, not removed.")


class TeamDetail(TeamRead):
    """One team: its parents up to the top, its sub-teams, its members —
    each said or inferred — what it owns, where each piece came from."""

    description: str | None
    attributes: dict[str, object]
    provenance: dict[str, object]
    ancestors: list[EntityBrief] = Field(description="Its parent, then theirs.")
    sub_teams: list[EntityBrief]
    members: list[Tie]
    owned: list[Tie] = Field(description="The surest first, up to 200.")


class PersonRead(BaseModel):
    """Someone who works there: what a directory says of them, their teams
    and manager, what their work shows they know."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    email: str | None
    job_title: str | None
    department: str | None
    active: bool | None = Field(description="Their account at a directory: on, off — or unknown.")
    bot: bool
    teams: list[EntityBrief]
    manager: EntityBrief | None
    report_count: int
    maintains: int = Field(description="The repositories, projects, services they maintain.")
    expertise: list[Expertise] = Field(description="The first three.")
    languages: list[str]
    last_activity_at: str | None


class PersonDetail(PersonRead):
    """One person: their teams — each said or inferred — their managers up
    to the top, their reports, what they maintain and own, everything their
    work shows they know."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    memberships: list[Tie]
    managers: list[EntityBrief] = Field(description="Their manager, then theirs.")
    reports: list[EntityBrief]
    maintained: list[Tie]
    owned: list[EntityBrief]
    contributions: list[Tie] = Field(description="contributes_to, the surest first.")
    all_expertise: list[Expertise]


class Responsibility(BaseModel):
    """Who owns and operates a thing, and who knows it — each with its
    origin: what a source says, what a rule inferred."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    owners: list[Tie] = Field(description="Its teams — or people.")
    leads: list[EntityBrief] = Field(description="Who leads its owning teams.")
    maintainers: list[Tie]
    experts: list[Tie] = Field(description="Whose work shows they know it, the surest first.")
    escalation_policy: str | None


# ── documentation and business knowledge (LEKA-366) ──────────────────────────


class DocumentRead(BaseModel):
    """A document: where it is kept, who wrote it and last changed it, how
    fresh it is, whose it is, what it describes."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    url: str | None
    tools: list[str] = Field(description="The sources' kinds it is read from: confluence, notion…")
    document_kind: str | None = Field(description="page, post, card, file, document.")
    space: EntityBrief | None
    freshness: str | None = Field(
        description="fresh (changed within 90 days), aging (within a year), stale — "
        "enrichment's, from when it last changed. None: no date known."
    )
    last_changed_at: str | None
    verified: bool | None = Field(description="Its tool says it is verified — Guru's — or not.")
    authors: list[EntityBrief]
    last_editor: EntityBrief | None
    owners: list[EntityBrief] = Field(description="Its teams — or people.")
    describes: list[EntityBrief] = Field(description="What it is about, the surest first.")


class DocumentDetail(DocumentRead):
    """One document: its pages above and below, everything it is tied to —
    each said by a source or inferred by a rule, how surely."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    verification_due_at: str | None
    ancestors: list[EntityBrief] = Field(description="Its parent page, then theirs.")
    children: list[EntityBrief]
    descriptions: list[Tie] = Field(description="What it describes, with origin and rule.")
    ownership: list[Tie]
    written_by: list[Tie]
    edited_by: list[Tie]
    links_to: list[Tie] = Field(description="The documents and spaces it links to.")
    linked_from: list[Tie] = Field(description="The documents linking to it.")
    mentions: list[Tie] = Field(description="The repositories, issues, pull requests it names.")


class KnowledgeSpaceRead(BaseModel):
    """Where documents are kept: how many, how fresh, whose, what it
    documents."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    url: str | None
    tools: list[str]
    space_kind: str | None = Field(
        description="space, database, topic, collection, shared_drive, document_library, onedrive."
    )
    description: str | None
    document_count: int = Field(description="Its documents, not removed.")
    freshness: dict[str, int] = Field(
        description="Its documents by freshness: fresh, aging, stale."
    )
    last_changed_at: str | None = Field(description="When its latest document changed.")
    owners: list[EntityBrief]
    describes: list[EntityBrief]
    maintainers: list[EntityBrief] = Field(description="Those who write and edit it most.")


class KnowledgeSpaceDetail(KnowledgeSpaceRead):
    """One space: everything it is tied to, its latest documents and its
    stalest."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    ownership: list[Tie]
    descriptions: list[Tie]
    maintained_by: list[Tie]
    recent: list[EntityBrief] = Field(description="Its ten latest changed documents.")
    stalest: list[EntityBrief] = Field(description="Its ten stale documents changed longest ago.")


class CoverageRead(BaseModel):
    """How much of one kind of thing is documented."""

    model_config = ConfigDict(frozen=True)

    type: EntityType
    total: int = Field(description="Not removed.")
    documented: int = Field(description="Described by a document or a space.")
    fresh: int = Field(description="Described by a document that is not stale.")


class DocumentationCoverage(BaseModel):
    """The documentation of the workspace: how much, how fresh, what it
    covers."""

    model_config = ConfigDict(frozen=True)

    documents: int
    spaces: int
    freshness: dict[str, int] = Field(
        description="Documents by freshness: fresh, aging, stale — unknown without a date."
    )
    unverified: int = Field(description="Documents their tool says need verifying.")
    coverage: list[CoverageRead]


class DocumentationGap(BaseModel):
    """A thing without documentation — or with only stale documentation."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    criticality: str | None
    owners: list[EntityBrief]
    documents: int = Field(description="The documents describing it: none, or only stale ones.")
    last_documented_at: str | None = Field(description="When its latest document changed.")


class BusinessRead(BaseModel):
    """A business capability — what the company does — or a business
    process — how: where it sits, whose it is, what supports it, what it
    uses."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    type: EntityType
    lifecycle: Lifecycle
    level: int | None
    criticality: str | None
    stage: str | None
    process_type: str | None = Field(
        description="A process's: process, activity… as its source says."
    )
    step: int | None = Field(description="An activity's place in its process.")
    parent: EntityBrief | None = Field(
        description="A capability's parent capability; an activity's process."
    )
    capabilities: list[EntityBrief] = Field(description="What a process realizes.")
    part_count: int = Field(description="Its sub-capabilities, or its activities.")
    process_count: int = Field(description="The processes realizing a capability.")
    supported_by: list[EntityBrief] = Field(description="The applications and services.")
    data_count: int = Field(description="The data it uses.")
    owners: list[EntityBrief] = Field(description="Its business owners: teams or people.")
    document_count: int = Field(description="The documents and spaces describing it.")


class BusinessPart(BaseModel):
    """A sub-capability, or an activity of a process: what supports it,
    what it uses, whose it is."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    step: int | None
    supported_by: list[EntityBrief]
    data: list[EntityBrief]
    owners: list[EntityBrief]


class BusinessDetail(BusinessRead):
    """One capability or process: its parents, its parts in order, the
    processes realizing it, the technology supporting it — and, through its
    applications, their services — the data it uses, its owners, its
    documentation: each said by a source or inferred by a rule."""

    description: str | None
    attributes: dict[str, object]
    provenance: dict[str, object]
    ancestors: list[EntityBrief] = Field(description="Its parent, then theirs.")
    parts: list[BusinessPart] = Field(description="Its activities by step, its sub-capabilities.")
    processes: list[EntityBrief]
    support: list[Tie] = Field(description="supported_by: its applications and services.")
    services: list[EntityBrief] = Field(description="The services of its applications.")
    data: list[Tie] = Field(description="uses: its tables, schemas, databases.")
    ownership: list[Tie]
    documentation: list[Tie] = Field(description="The documents and spaces describing it.")


class BusinessTie(BaseModel):
    """A capability or a process a thing matters to, and how: it supports
    or holds what they rely on — itself, what holds it, or what depends on
    it."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    relation: RelationshipType = Field(description="supported_by, uses.")
    via: EntityBrief | None = Field(
        description="What they rely on, when not the thing itself: its service, its "
        "application, what depends on it."
    )
    path: Literal["direct", "contained", "dependent"]
    origin: str
    rule: str
    confidence: float


class BusinessContext(BaseModel):
    """What a technical thing — a service, an application, a table, a
    resource — means to the business: the capabilities and processes that
    rely on it, directly or through what holds it or depends on it."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    capabilities: list[BusinessTie]
    processes: list[BusinessTie]


# ── incidents, changes and deployments (LEKA-367) ────────────────────────────


class TimelineStep(BaseModel):
    """A moment of an incident's, a change's, a deployment's life: what its
    sources date — opened, acknowledged, resolved; planned, started,
    finished — or a state LEKA saw it take, at a build."""

    model_config = ConfigDict(frozen=True)

    at: datetime
    step: str = Field(
        description="opened, detected, acknowledged, resolved, closed, planned_start, "
        "planned_end, started, finished — or state."
    )
    state: str | None = Field(description="For a state: the one it took.")
    origin: Literal["source", "model"] = Field(
        description="source: a date its sources give; model: when a build saw the state."
    )


class TimelineEvent(BaseModel):
    """Something that happened: an incident opened or resolved, a
    deployment, a change, a release, a merge — and, in a thing's timeline,
    what of it it happened to."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    kind: Literal[
        "incident_opened", "incident_resolved", "deployment", "change", "release", "merge"
    ]
    at: datetime
    state: str | None
    environment: str | None
    via: EntityBrief | None = Field(
        description="What of the thing it happened to: its repository, one of its services."
    )


class Timeline(BaseModel):
    """What happened, the latest first: around a thing — itself, what is
    part of it, what affects it — or in the whole workspace."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief | None
    since: datetime
    until: datetime
    events: list[TimelineEvent]
    truncated: bool = Field(description="More happened than the limit.")


class Impact(BaseModel):
    """What an incident reaches: what it affects, what depends on that, the
    applications holding them, and the business relying on them."""

    model_config = ConfigDict(frozen=True)

    affected: list[EntityBrief]
    dependents: list[EntityBrief] = Field(description="What depends on them, two steps at most.")
    applications: list[EntityBrief]
    capabilities: list[BusinessTie]
    processes: list[BusinessTie]


class DisputeSource(BaseModel):
    """A source saying one side of a dispute (LEKA-382): which, what kind,
    whether it reads, when it last did — and when it said this."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID | None
    kind: str | None
    name: str | None
    status: str | None
    synced_at: datetime | None
    observed_at: datetime | None = Field(description="When this source last said this value.")


class DisputeSide(BaseModel):
    """One value of a dispute, and who says it. For a relationship, the
    other end (`ref_id`) and how the tie was made."""

    model_config = ConfigDict(frozen=True)

    value: JsonValue
    ref_id: uuid.UUID | None = None
    origin: str | None = Field(default=None, description="A relationship's: stated, inferred…")
    confidence: float | None = None
    sources: list[DisputeSource]
    # A relationship's ties that say it: {from, to, type} — what a decision
    # refutes when it keeps another side.
    edges: list[dict[str, str]] = Field(default_factory=list)


class Dispute(BaseModel):
    """What the model's sources disagree on (LEKA-382): an attribute of one
    thing — the sources of acme/backend say 99.95, those of acme-eu 99.9 —
    or a relationship it has one of — two owners, two managers. `chosen`
    is what the model shows; `settled`, the decision behind it when one was
    taken."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(description="attribute or relationship.")
    entity: EntityBrief
    about: str = Field(description="The attribute — or the relationship's role: owner, manager.")
    relationship: str | None = Field(description="The relationship's kind, for one.")
    chosen: JsonValue
    sides: list[DisputeSide]
    settled: dict[str, object] | None = None


class EntityStanding(BaseModel):
    """What the model holds around one thing (LEKA-379): how critical its
    sources say it is, the documents describing it and how many are not
    stale, when the latest changed, whether the business holds it."""

    model_config = ConfigDict(frozen=True)

    criticality: str | None
    # The attributes its sources state (LEKA-380): a validated fact that
    # would replace one of these overrides a source.
    stated: tuple[str, ...] = ()
    lifecycle: Lifecycle
    documents: int
    fresh_documents: int
    last_documented_at: str | None
    business: bool = Field(
        description="Part of an application, or tied to a capability or a process."
    )


class ChangeTouch(BaseModel):
    """What a change was made to (LEKA-378): a service, an application, a
    resource — said by its source (part of it, affecting it, deployed to
    it), or the service a repository it was made in is part of."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    how: str = Field(description="part_of, affects, deployed_to — or via_repository.")
    criticality: str | None


class ChangeReach(BaseModel):
    """What depends on what a change touched: how far, through which."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    distance: int = Field(description="1: depends on what it touched; 2: one step further.")
    through: EntityBrief = Field(description="The touched thing it depends on.")
    criticality: str | None


class ChangeIncident(BaseModel):
    """An incident after a change, on what it touched or reached — or that
    says the change caused it, whenever it opened."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    opened_at: datetime | None
    severity: str | None
    state: str | None
    on: EntityBrief | None = Field(description="What of the change's footprint it affects.")
    stated: bool = Field(description="Its source says the change caused it.")


class ChangeFootprint(BaseModel):
    """A change, and what the company model says it reaches (LEKA-378):
    what it was made to, what depends on that two steps up, the
    applications and the business holding them, the incidents that
    followed. Facts only — how much it matters is judged elsewhere
    (leka.intelligence)."""

    model_config = ConfigDict(frozen=True)

    change: EntityBrief
    kind: str = Field(description="deployment, change, release or pull_request.")
    at: datetime
    state: str | None
    environment: str | None
    details: dict[str, str] = Field(
        description="What its source says of it: ref, commit, version, url, changes, risk."
    )
    sources: list[str] = Field(description="The kinds of the sources that show it.")
    source_ids: list[str]
    touched: list[ChangeTouch]
    reached: list[ChangeReach]
    applications: list[EntityBrief]
    capabilities: list[BusinessTie]
    processes: list[BusinessTie]
    incidents: list[ChangeIncident]


class IncidentRead(BaseModel):
    """An incident: how bad, where it stands, when it opened and was
    handled, what it affects, who leads it, what is said or suspected to
    have caused it."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    url: str | None
    tools: list[str]
    state: str | None = Field(description="open, in_progress, closed.")
    priority: str | None
    severity: str | None
    urgency: str | None
    opened_at: datetime | None
    acknowledged_at: str | None
    resolved_at: str | None
    time_to_acknowledge_minutes: int | None
    duration_minutes: int | None
    affects: list[EntityBrief]
    commander: EntityBrief | None
    assignees: list[EntityBrief]
    causes: list[EntityBrief] = Field(description="Said first, then suspected — the surest first.")


class IncidentDetail(IncidentRead):
    """One incident: its timeline, everything it is tied to — each said or
    inferred — what changed before it, and what it reaches."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    timeline: list[TimelineStep]
    affected: list[Tie]
    people: list[Tie] = Field(description="Who leads it, is assigned to it, reported it.")
    suspected_causes: list[Tie] = Field(description="caused_by: said, or `preceded`.")
    changed_before: list[TimelineEvent] = Field(
        description="Deployments, changes, releases, merges on what it affects — the 72 hours "
        "before it opened."
    )
    impact: Impact


class DeploymentRead(BaseModel):
    """A deployment: what to where, how it went, when, by whom."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    url: str | None
    tools: list[str]
    state: str | None = Field(
        description="pending, in_progress, succeeded, failed, canceled, inactive."
    )
    environment: str | None
    production: bool | None
    ref: str | None
    sha: str | None
    deployed_at: datetime | None
    started_at: str | None
    finished_at: str | None
    duration_minutes: int | None
    repository: EntityBrief | None
    services: list[EntityBrief] = Field(description="Its own, and its repository's.")
    deployer: EntityBrief | None
    incident_count: int = Field(description="The incidents said or suspected to follow from it.")


class DeploymentDetail(DeploymentRead):
    """One deployment: each status with when, what it shipped, where it went,
    the incidents said or suspected to follow from it."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    status_history: list[TimelineStep]
    ships: list[Tie] = Field(description="deploys: its commit, its release.")
    environments: list[EntityBrief]
    incidents: list[Tie]


class ChangeRead(BaseModel):
    """A change: of what type, how risky, where it stands, when, what it
    affects, who made it and asked for it."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    key: str
    name: str
    lifecycle: Lifecycle
    url: str | None
    tools: list[str]
    state: str | None = Field(
        description="requested, scheduled, in_progress, completed, failed, canceled."
    )
    change_type: str | None
    risk: str | None
    environment: str | None
    changed_at: datetime | None
    planned_start_at: str | None
    planned_end_at: str | None
    affects: list[EntityBrief]
    assignee: EntityBrief | None
    requester: EntityBrief | None
    incident_count: int


class ChangeDetail(ChangeRead):
    """One change: its timeline, what it affects, who made and asked for
    it, the incidents said or suspected to follow from it."""

    attributes: dict[str, object]
    provenance: dict[str, object]
    timeline: list[TimelineStep]
    affected: list[Tie]
    people: list[Tie]
    incidents: list[Tie]


# ── relationships (LEKA-368) ─────────────────────────────────────────────────


class GraphRelationshipRead(RelationshipRead):
    """A relationship of the graph: both ends named, where it came from,
    when it first appeared and last changed."""

    from_entity: EntityBrief
    to_entity: EntityBrief
    provenance: list[dict[str, object]]
    first_seen_at: datetime | None
    changed_at: datetime | None


class RelationshipChangeRead(BaseModel):
    """A relationship that appeared, changed or went at a build."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    type: str
    change: Literal["added", "changed", "removed"]
    from_entity: EntityBrief | None
    to_entity: EntityBrief | None
    before: dict[str, object] | None = Field(
        description="{confidence, origin, rule, environments}; None when it was not there."
    )
    after: dict[str, object] | None
    recorded_at: datetime
    run_id: uuid.UUID | None


class RelationshipIssueRead(BaseModel):
    """What the last build found wrong with a relationship."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    type: str
    issue: Literal["wrong_end", "cycle_broken", "cycle", "several_targets"]
    severity: Literal["error", "warning"] = Field(
        description="error: dropped from the graph; warning: kept — but a cycle_broken's link, "
        "dropped."
    )
    from_entity: EntityBrief | None
    to_entity: EntityBrief | None
    origin: str
    rule: str
    confidence: float
    detail: dict[str, object] = Field(
        description="wrong_end: {end, found, expected}; cycle, cycle_broken: {members}; "
        "several_targets: {targets}."
    )
    found_at: datetime


# ── the knowledge graph: search, walks, paths, views (LEKA-369) ──────────────


class SearchHit(BaseModel):
    """An entity search found."""

    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    score: float = Field(
        description="How well it matches: the very name, then a name it starts, then the words."
    )
    holder: EntityBrief | None = Field(
        description="Where it is: what it is part of, a child or a member of — the surest."
    )
    sources: list[str] = Field(description="The kinds of the sources that show it.")


class SearchResults(BaseModel):
    """What a search found: entities, the best first, and what they say of
    one another."""

    model_config = ConfigDict(frozen=True)

    query: str
    entities: list[SearchHit]
    relationships: list[GraphRelationshipRead] = Field(
        description="The relationships among the entities found."
    )


class GraphNodeRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity: EntityBrief
    depth: int = Field(description="Steps from the nearest root; 0 for a root.")
    sources: list[str] = Field(description="The kinds of the sources that show it.")


class GraphRead(BaseModel):
    """What a walk reached from its roots: the entities and the
    relationships among them."""

    model_config = ConfigDict(frozen=True)

    roots: list[EntityBrief]
    depth: int
    direction: Literal["outgoing", "incoming", "both"]
    nodes: list[GraphNodeRead] = Field(description="The roots first, then the nearest.")
    relationships: list[RelationshipRead]
    truncated: bool = Field(description="More was reached than a response holds.")


class PathRead(BaseModel):
    """A way from one entity to another: the entities in order, and the
    relationship between each and the next — read either way."""

    model_config = ConfigDict(frozen=True)

    entities: list[EntityBrief]
    relationships: list[RelationshipRead]


class PathsRead(BaseModel):
    """The shortest ways between two entities."""

    model_config = ConfigDict(frozen=True)

    start: EntityBrief
    end: EntityBrief
    length: int | None = Field(
        description="Steps of the shortest; none when none was found within max_depth."
    )
    paths: list[PathRead]
    truncated: bool = Field(description="The walk stopped before it was done: too much reached.")


class ViewLayerRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    types: list[EntityType] = Field(description="What it holds; none for a row no source fills.")
    total: int
    shown: int


class ViewNodeRead(BaseModel):
    """A box of a view: an entity, or a provider's cloud resources together."""

    model_config = ConfigDict(frozen=True)

    id: str
    type: str = Field(description="The entity's type — or provider.")
    layer: str
    name: str
    status: str | None = Field(
        description="operational, attention, incident, unmonitored — none when it has no state."
    )
    entity_id: uuid.UUID | None
    key: str | None
    detail: str | None = Field(description="A provider's region; an engine, a class, a title.")
    count: int = Field(description="A provider's resources; 1 for an entity.")
    environment: str | None
    team: EntityBrief | None
    deduced: bool = Field(
        default=False,
        description="Its state is deduced — from what runs it — not a tool's word (LEKA-369).",
    )


class ViewEdgeRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_id: str
    to_id: str
    type: str
    status: str | None = Field(description="The worse state of its two ends.")


class KindCoverageRead(BaseModel):
    """How well LEKA knows one kind of thing."""

    model_config = ConfigDict(frozen=True)

    type: EntityType
    total: int
    owned: int | None = Field(description="With an owner; none where it does not apply.")
    documented: int | None = Field(description="Described by a document.")
    corroborated: int = Field(description="Said by two sources or more.")
    connected: int = Field(description="Tied to anything at all.")


class ViewSourceRead(BaseModel):
    """A source, and how many of the kinds asked it shows."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    kind: str
    entities: int


class LandscapeViewRead(BaseModel):
    """A landscape of the company: its layers, their boxes and the lines
    between them, how well it is known, and where it comes from."""

    model_config = ConfigDict(frozen=True)

    view: str
    built_at: datetime | None = Field(description="When the model was last built.")
    layers: list[ViewLayerRead]
    nodes: list[ViewNodeRead]
    edges: list[ViewEdgeRead]
    coverage: list[KindCoverageRead]
    sources: list[ViewSourceRead]


class ArchitectureCardRead(BaseModel):
    """One thing of the architecture: an entity, or a monitoring tool."""

    model_config = ConfigDict(frozen=True)

    id: str
    column: str = Field(description="code, services, data, cloud or external.")
    group: str = Field(description="Where it is from in its column: github, aws…")
    kind: str = Field(
        description="What it is, in one word: api, web, worker, proxy, database, cache, "
        "storage, instance, bucket, email, monitoring…"
    )
    type: str = Field(description="The entity's type; `tool` for a monitoring tool.")
    name: str
    entity_id: uuid.UUID | None
    key: str | None
    status: str | None = Field(description="operational, attention, incident, unmonitored.")
    deduced: bool = Field(description="Its state is deduced from what runs it.")
    why: str | None = Field(
        description="What the deduced state was read from, as enrichment wrote it (English)."
    )
    technology: list[str]
    description: str | None
    environment: str | None
    region: str | None
    url: str | None = Field(description="Where it is reached, or where it is kept.")
    team: EntityBrief | None
    repository_id: str | None = Field(description="The card of its code.")
    host_id: str | None = Field(description="The card of what runs it, when known.")
    deployment: str | None = Field(description="How its last deployment went: succeeded, failed…")
    stats: dict[str, int] = Field(
        description="What the sources count of it: commits, pull_requests, tables, "
        "size_bytes, buckets."
    )
    evidence: list[str] = Field(description="The files and lines that say what it is.")
    sources: list[str] = Field(description="The kinds of the sources that show it.")
    facts: dict[str, object] = Field(
        description="What its sources say of it in detail: an instance's type, zone and "
        "addresses, a database's engine and storage, a service's image and deployment.",
    )
    parts: list[dict[str, object]] = Field(
        description="A module's parts — Leka/api's connectors, ingestion — each with its "
        "path, files, own parts and their names.",
    )
    files: list[str] = Field(description="A small module's files.")
    maintainers: list[EntityBrief] = Field(description="Who maintains it, by their work.")


class ArchitectureFlowRead(BaseModel):
    """What one entry goes through, step by step — a request from the proxy
    to the database, a job from the worker to its stores."""

    model_config = ConfigDict(frozen=True)

    entries: list[str] = Field(description="The cards it starts from: alike ones together.")
    steps: list[ArchitectureLinkRead]


class ArchitectureCheckRead(BaseModel):
    """What to confirm: what is wrong, deduced, inferred, unowned, unwatched
    or tied to nothing."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(
        description="incident, attention, deduced, inferred, unmonitored, no_team, unlinked."
    )
    card_id: str
    other_id: str | None
    role: str | None
    rule: str | None
    confidence: float | None


class ArchitectureSourceRead(BaseModel):
    """A source the architecture was read from: what it is, when it last
    read, how much it shows."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    kind: str
    name: str
    status: str
    last_synced_at: datetime | None
    entities: int


class ArchitectureLinkRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_id: str
    to_id: str
    role: str = Field(
        description="source_code, routes, calls, queue, cache, stores, files, email, uses, "
        "depends, deployed_on, hosted_on, monitored_by, part_of."
    )
    origin: str = Field(
        description="stated by a source, inferred by enrichment, or accepted (LEKA-380)."
    )
    rule: str = Field(
        description="What inferred it: public_address, deployed_together, only_instance…"
    )
    confidence: float
    evidence: str | None
    status: str | None = Field(description="The worse of its ends' states.")


class ArchitectureBundleRead(BaseModel):
    """A card's links to one other column, together: one arrow, named by
    what most of them are, until the card is chosen."""

    model_config = ConfigDict(frozen=True)

    from_id: str
    column: str
    role: str
    roles: list[str]
    targets: list[str] = Field(description="The cards it reaches there.")


class ArchitectureGroupRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    column: str
    name: str = Field(description="github, gitlab, aws, azure, gcp, other — or the column's.")
    regions: list[str]
    total: int
    shown: int


class ArchitectureFiguresRead(BaseModel):
    """How many of each kind the company has — all of them, not only those
    drawn."""

    model_config = ConfigDict(frozen=True)

    services: int
    applications: int
    repositories: int
    databases: int
    stores: int
    cloud_resources: int
    providers: dict[str, int] = Field(description="The cloud resources, by provider.")
    external: int
    teams: int
    tables: int


class ArchitectureRankRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    card_id: str
    name: str
    kind: str
    count: int = Field(description="How many cards rely on it.")


class ArchitectureRead(BaseModel):
    """What the company runs, in columns — its code, its services, its data,
    its cloud, what it relies on outside — each thing's state, the links
    between them named, and the figures around them (LEKA-369)."""

    model_config = ConfigDict(frozen=True)

    built_at: datetime | None
    environment: str | None = Field(description="The environment shown; none: all.")
    environments: list[str]
    groups: list[ArchitectureGroupRead]
    cards: list[ArchitectureCardRead]
    links: list[ArchitectureLinkRead]
    bundles: list[ArchitectureBundleRead]
    figures: ArchitectureFiguresRead
    health: dict[str, int] = Field(
        description="The services', stores' and resources' states, counted."
    )
    services_by_status: dict[str, int]
    top_dependencies: list[ArchitectureRankRead]
    detailed: bool = Field(description="Every card, and what follows.")
    flows: list[ArchitectureFlowRead] = Field(description="Detailed: what each entry goes through.")
    checks: list[ArchitectureCheckRead] = Field(description="Detailed: what to confirm.")
    sources: list[ArchitectureSourceRead] = Field(description="Detailed: what it was read from.")


class KnowledgeCoverageRead(BaseModel):
    """How well LEKA knows the company, kind by kind, and from which sources."""

    model_config = ConfigDict(frozen=True)

    built_at: datetime | None
    kinds: list[KindCoverageRead]
    sources: list[ViewSourceRead]
