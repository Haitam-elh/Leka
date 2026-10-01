"""The registry of the company model (LEKA-361): what kinds of things a
company is made of, what each says about itself, and how they relate.

    ENTITY_KINDS        each EntityType: its version, its category, the
                        schema its attributes are checked against, the
                        ingestion types it is built from
    RELATIONSHIP_KINDS  each RelationshipType, and the relationships of
                        enrichment (LEKA-359) it is built from

VERSIONED. A kind's `version` is raised when its schema changes in a way
that changes what is kept; every entity says which it was checked against
(`schema_version`). MODEL_VERSION is raised when anything here changes what
a build makes: the next build remakes every entity — their ids, histories
and lifecycles kept.

EXTENSIBLE WITHOUT BREAKING. A schema declares what it knows and lets the
rest through (`extra="allow"`): a connector that learns a new attribute
adds it without a change here, and an entity made before a field was
declared still reads. A declared field whose value does not fit — a number
where a list is expected — is dropped from the entity, said in the build's
counts, never written wrong. A new kind is an entry here and a value of the
enum (a CHECK constraint, docs/adr/006-enum-storage.md): no new table.

Rules: docs/company-model.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from leka.knowledge.models import EntityType, RelationshipType

# 1: the first company model.
# 2: applications and environments, where things run, how critical they are,
#    relationships true in some environments only, sources' disagreements
#    kept (LEKA-362).
# 3: what resources are in — cloud accounts, resource groups — resources'
#    class, place and cluster; a terminated resource archived (LEKA-363).
# 4: databases' schemas and data objects, foreign keys and what views read,
#    data classification (LEKA-364).
# 5: people and teams — a directory's titles and departments, who reports
#    to whom, teams' hierarchy, what people work on (LEKA-365).
MODEL_VERSION = 5


class Attributes(BaseModel):
    """What every kind may say: where to see it, what state it is in, how
    alive it is (enrichment's measures)."""

    model_config = ConfigDict(extra="allow")

    url: str | None = None
    description: str | None = None
    state: str | None = None
    lifecycle: str | None = None
    last_activity_at: str | None = None
    activity_90d: int | None = None


class Landscape(Attributes):
    """What services and applications share (LEKA-362): how critical — on
    LEKA's scale, the source's word beside — where in their life, where
    they run."""

    criticality: str | None = None
    criticality_raw: str | None = None
    stage: str | None = None
    stage_raw: str | None = None
    environments: list[str] | None = None
    point_of_contact: str | None = None


class ServiceAttributes(Landscape):
    environment: str | None = None
    service_type: str | None = None
    languages: list[str] | None = None
    escalation_policy: str | None = None
    display_name: str | None = None
    runbook_url: str | None = None
    repository_url: str | None = None
    dashboard_url: str | None = None
    docs_url: str | None = None
    incidents_90d: int | None = None
    open_incidents: int | None = None
    mttr_minutes: int | None = None


class ApplicationAttributes(Landscape):
    """A group of services the company names as one: a product, a system."""


class RepositoryAttributes(Attributes):
    visibility: str | None = None
    default_branch: str | None = None
    language: str | None = None
    topics: list[str] | None = None
    fork: bool | None = None


class WorkAttributes(Attributes):
    """Issues and pull requests: tickets, tasks, changes under review."""

    priority: str | None = None
    category: str | None = None
    labels: list[str] | None = None
    components: list[str] | None = None
    stale: bool | None = None
    cycle_time_hours: float | None = None


class CommitAttributes(Attributes):
    category: str | None = None
    change_type: str | None = None


class IncidentAttributes(Attributes):
    priority: str | None = None
    duration_minutes: int | None = None


class PersonAttributes(Attributes):
    """Someone who works there (LEKA-365): their address, what a directory
    says of them, whether a bot, what their work shows they know."""

    email: str | None = None
    job_title: str | None = None
    department: str | None = None
    location: str | None = None
    active: bool | None = None
    user_type: str | None = None
    directory: str | None = None
    bot: bool | None = None
    # Enrichment's, from their work: [{key, name, type, items, roles, last_at}].
    expertise: list[dict[str, object]] | None = None
    languages: list[str] | None = None


class TeamAttributes(Attributes):
    """A team — or a department a directory names (LEKA-365)."""

    team_type: str | None = None
    slug: str | None = None
    privacy: str | None = None


class Placed(Attributes):
    """What every cloud thing says of where it is (LEKA-363): its provider,
    the account, subscription or project it is in, its region; the
    environment it runs in, how critical it is; its tags as they are."""

    provider: str | None = None
    account: str | None = None
    region: str | None = None
    environment: str | None = None
    criticality: str | None = None
    tags: dict[str, object] | None = None


class ResourceAttributes(Placed):
    """Cloud resources and databases: what kind — instance, function,
    cluster, network, load balancer, bucket, database — of which class —
    compute, network, storage, database — the provider's own type, where
    exactly, how reachable."""

    resource_kind: str | None = None
    resource_class: str | None = None
    resource_type: str | None = None
    resource_group: str | None = None
    zone: str | None = None
    exposure: str | None = None
    instance_type: str | None = None
    engine: str | None = None
    version: str | None = None
    runtime: str | None = None
    endpoint: str | None = None
    created_at: str | None = None


class Classified(Attributes):
    """What a database, a schema or a data object says of the data it holds
    (LEKA-364): what kinds — contact, identity, location, financial,
    credential, health, personal — how sensitive, whether personal data."""

    data_categories: list[str] | None = None
    classification: str | None = None
    personal_data: bool | None = None
    engine: str | None = None
    owner_role: str | None = None


class DatabaseAttributes(ResourceAttributes):
    """A database: a cloud instance, or the database a source reads on a
    server — its host, port and name — and the data it holds."""

    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    data_categories: list[str] | None = None
    classification: str | None = None
    personal_data: bool | None = None


class SchemaAttributes(Classified):
    """A schema of a database — a MySQL or MongoDB database, on a server."""


class DataObjectAttributes(Classified):
    """A table, a view, a materialized view, a collection: its columns and
    keys, its size, what each column holds."""

    object_kind: str | None = None
    # Not `schema`: BaseModel has one.
    schema_name: str | None = None
    columns: list[str] | None = None
    primary_key: list[str] | None = None
    column_categories: dict[str, str] | None = None
    estimated_rows: int | None = None
    size_bytes: int | None = None


class CloudAccountAttributes(Placed):
    """An AWS account, an Azure subscription, a Google Cloud project: what
    resources are in — its id, its state, what is above it."""

    account_type: str | None = None
    account_id: str | None = None
    organization: str | None = None
    management_account: str | None = None
    tenant: str | None = None
    parent: str | None = None


class ResourceGroupAttributes(Placed):
    """An Azure resource group: resources grouped in a subscription."""

    resource_group: str | None = None


class EnvironmentAttributes(Attributes):
    """Production, staging, development, test: where things run."""


# A kind's schema: named here, as `type` inside EntityKind is its field.
Schema = type[Attributes]


@dataclass(frozen=True)
class EntityKind:
    type: EntityType
    version: int
    # How the company is read: organisation, applications, delivery,
    # operations, infrastructure, knowledge.
    category: str
    attributes: Schema
    # The ingestion types (docs/normalisation.md § 2) an entity of this kind
    # is built from.
    built_from: tuple[str, ...]


ENTITY_KINDS: dict[EntityType, EntityKind] = {
    kind.type: kind
    for kind in (
        EntityKind(EntityType.PERSON, 2, "organisation", PersonAttributes, ("person",)),
        EntityKind(EntityType.TEAM, 2, "organisation", TeamAttributes, ("team",)),
        EntityKind(
            EntityType.APPLICATION, 1, "applications", ApplicationAttributes, ("application",)
        ),
        EntityKind(EntityType.SERVICE, 2, "applications", ServiceAttributes, ("service",)),
        EntityKind(EntityType.REPOSITORY, 1, "applications", RepositoryAttributes, ("repository",)),
        EntityKind(EntityType.PROJECT, 1, "delivery", Attributes, ("project",)),
        EntityKind(EntityType.ISSUE, 1, "delivery", WorkAttributes, ("issue",)),
        EntityKind(EntityType.PULL_REQUEST, 1, "delivery", WorkAttributes, ("pull_request",)),
        EntityKind(EntityType.COMMIT, 1, "delivery", CommitAttributes, ("commit",)),
        EntityKind(EntityType.RELEASE, 1, "delivery", Attributes, ("release",)),
        EntityKind(EntityType.DEPLOYMENT, 1, "delivery", Attributes, ("deployment",)),
        EntityKind(EntityType.INCIDENT, 1, "operations", IncidentAttributes, ("incident",)),
        EntityKind(
            EntityType.INFRA_RESOURCE, 3, "infrastructure", ResourceAttributes, ("infra_resource",)
        ),
        EntityKind(EntityType.DATABASE, 4, "data", DatabaseAttributes, ("database",)),
        EntityKind(EntityType.SCHEMA, 1, "data", SchemaAttributes, ("schema",)),
        EntityKind(EntityType.DATA_OBJECT, 1, "data", DataObjectAttributes, ("data_object",)),
        EntityKind(
            EntityType.CLOUD_ACCOUNT,
            1,
            "infrastructure",
            CloudAccountAttributes,
            ("cloud_account",),
        ),
        EntityKind(
            EntityType.RESOURCE_GROUP,
            1,
            "infrastructure",
            ResourceGroupAttributes,
            ("resource_group",),
        ),
        EntityKind(
            EntityType.ENVIRONMENT, 1, "infrastructure", EnvironmentAttributes, ("environment",)
        ),
        EntityKind(EntityType.DOCUMENT, 1, "knowledge", Attributes, ("document",)),
    )
}

# Ingestion type → the kind built from it.
BUILT_FROM: dict[str, EntityKind] = {
    source: kind for kind in ENTITY_KINDS.values() for source in kind.built_from
}
# What normalisation makes and the model leaves out, on purpose: a branch is
# a short-lived name, not a part of the company. Any other type is a kind
# missing here — tests/test_company_model.py says which.
NOT_MODELLED = frozenset({"branch"})


@dataclass(frozen=True)
class RelationshipKind:
    type: RelationshipType
    version: int
    # The relationships of enrichment (docs/enrichment.md) it is built from.
    built_from: tuple[str, ...]


RELATIONSHIP_KINDS: dict[RelationshipType, RelationshipKind] = {
    kind.type: kind
    for kind in (
        RelationshipKind(RelationshipType.PART_OF, 1, ("part_of",)),
        RelationshipKind(RelationshipType.CHILD_OF, 1, ("child_of",)),
        RelationshipKind(RelationshipType.DEPENDS_ON, 1, ("depends_on",)),
        RelationshipKind(RelationshipType.OWNED_BY, 1, ("owned_by",)),
        RelationshipKind(RelationshipType.MAINTAINED_BY, 1, ("maintained_by",)),
        RelationshipKind(RelationshipType.MEMBER_OF, 1, ("member_of",)),
        RelationshipKind(RelationshipType.AUTHORED_BY, 1, ("authored_by", "committed_by")),
        RelationshipKind(RelationshipType.ASSIGNED_TO, 1, ("assigned_to",)),
        RelationshipKind(RelationshipType.REVIEWED_BY, 1, ("reviewed_by",)),
        RelationshipKind(RelationshipType.REPORTED_BY, 1, ("reported_by", "created_by")),
        RelationshipKind(RelationshipType.LED_BY, 1, ("led_by",)),
        RelationshipKind(RelationshipType.AFFECTS, 1, ("affects",)),
        RelationshipKind(RelationshipType.RESOLVES, 1, ("resolves",)),
        RelationshipKind(RelationshipType.IMPLEMENTS, 1, ("implements",)),
        RelationshipKind(RelationshipType.MERGES, 1, ("merges",)),
        RelationshipKind(RelationshipType.MENTIONS, 1, ("mentions",)),
        RelationshipKind(RelationshipType.IN_NETWORK, 1, ("in_network",)),
        RelationshipKind(RelationshipType.RUNS_IN, 1, ("runs_in",)),
        RelationshipKind(RelationshipType.REFERENCES, 1, ("references",)),
        RelationshipKind(RelationshipType.READS_FROM, 1, ("reads_from",)),
        RelationshipKind(RelationshipType.REPORTS_TO, 1, ("reports_to",)),
        RelationshipKind(RelationshipType.CONTRIBUTES_TO, 1, ("contributes_to",)),
        RelationshipKind(RelationshipType.OWNS, 1, ()),
        RelationshipKind(RelationshipType.DEPLOYED_TO, 1, ()),
        RelationshipKind(RelationshipType.CAUSED_BY, 1, ()),
    )
}

RELATIONSHIP_FROM: dict[str, RelationshipType] = {
    source: kind.type for kind in RELATIONSHIP_KINDS.values() for source in kind.built_from
}


def clean(kind: EntityKind, attributes: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    """An entity's attributes, checked against its kind's schema: what fits,
    and the names of the declared fields dropped for not fitting."""
    dropped: list[str] = []
    candidate = dict(attributes)
    for _ in range(len(candidate) + 1):
        try:
            checked = kind.attributes.model_validate(candidate)
        except ValidationError as error:
            wrong = {str(issue["loc"][0]) for issue in error.errors() if issue["loc"]}
            if not wrong:
                return {}, sorted(candidate)
            dropped += sorted(wrong)
            candidate = {k: v for k, v in candidate.items() if k not in wrong}
            continue
        return checked.model_dump(exclude_none=True), dropped
    return {}, sorted(attributes)
