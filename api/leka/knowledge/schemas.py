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
