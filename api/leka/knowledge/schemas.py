"""Types the knowledge module exposes: the company model as it is read.

The per-type validation of `attributes` is the registry's (registry.py):
the database cannot check what is inside a JSONB column —
docs/adr/003-entity-model.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    origin: str = Field(description="stated by a source, or inferred by an enrichment rule.")
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
    type: RelationshipType
    version: int
    built_from: list[str]


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
        description="source: a catalogue or a tag said it; enrichment: its parts show it."
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
    origin: str = Field(description="stated, inferred.")
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
