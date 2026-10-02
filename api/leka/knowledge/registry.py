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
# 6: knowledge spaces, documents' freshness, what each describes, who last
#    edited it; business capabilities and processes, the applications and
#    data they rely on (LEKA-366).
# 7: incidents, changes and deployments — when each happened, its states,
#    what it touched and shipped, what caused an incident; the dates of
#    releases and pull requests; when each event occurred (LEKA-367).
# 8: relationships checked against their kinds' contracts — what breaks one
#    dropped, what contradicts itself said or broken — and their history:
#    when each appeared, changed, went (LEKA-368).
MODEL_VERSION = 8


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
    """Issues and pull requests: tickets, tasks, changes under review — and
    when a pull request was opened, merged, closed (LEKA-367)."""

    priority: str | None = None
    category: str | None = None
    labels: list[str] | None = None
    components: list[str] | None = None
    stale: bool | None = None
    cycle_time_hours: float | None = None
    created_at: str | None = None
    merged_at: str | None = None
    closed_at: str | None = None


class CommitAttributes(Attributes):
    category: str | None = None
    change_type: str | None = None


class IncidentAttributes(Attributes):
    """An incident (LEKA-367): how urgent and severe, its tool's number,
    whether customers were hit; when it was opened, detected, acknowledged
    and resolved — its records' dates — and how long each took."""

    priority: str | None = None
    duration_minutes: int | None = None
    urgency: str | None = None
    severity: str | None = None
    incident_number: int | None = None
    customer_impacted: bool | None = None
    created_at: str | None = None
    detected_at: str | None = None
    acknowledged_at: str | None = None
    resolved_at: str | None = None
    closed_at: str | None = None
    time_to_acknowledge_minutes: int | None = None


class DeploymentAttributes(Attributes):
    """A deployment (LEKA-367): where to — its environment, canonical when
    known, production or not — what — its commit, its ref — how it went,
    each status with when; when it was made, started and finished."""

    environment: str | None = None
    production: bool | None = None
    sha: str | None = None
    ref: str | None = None
    task: str | None = None
    environment_url: str | None = None
    status_history: list[dict[str, object]] | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_minutes: int | None = None


class ChangeAttributes(Attributes):
    """A change (LEKA-367): of what type — normal, standard, emergency, a
    deployment — how risky, how far it went; when it was asked, planned,
    made."""

    change_type: str | None = None
    risk: str | None = None
    priority: str | None = None
    environment: str | None = None
    created_at: str | None = None
    planned_start_at: str | None = None
    planned_end_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ReleaseAttributes(Attributes):
    """A release: its tag, and when it was made and published (LEKA-367)."""

    tag: str | None = None
    draft: bool | None = None
    prerelease: bool | None = None
    created_at: str | None = None
    published_at: str | None = None


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


class DocumentAttributes(Attributes):
    """A page, a post, a card, a file (LEKA-366): what kind; how fresh —
    enrichment's, from when it last changed (`last_activity_at`); whether
    its tool says it is verified, and when it wants it verified again; its
    version, its type and size, where it is in its drive."""

    document_kind: str | None = None
    tools: list[str] | None = None
    freshness: str | None = None
    verified: bool | None = None
    verification_due_at: str | None = None
    version: int | None = None
    mime_type: str | None = None
    size: int | None = None
    path: str | None = None


class KnowledgeSpaceAttributes(Attributes):
    """Where documents are kept (LEKA-366): a Confluence space, a Notion
    database, a Slab topic, a Guru collection, a shared drive, a SharePoint
    library or a OneDrive — its tool's word for it, its key."""

    space_kind: str | None = None
    space_type: str | None = None
    space_key: str | None = None
    tools: list[str] | None = None


class BusinessAttributes(Attributes):
    """A business capability — what the company does — or a business
    process and its activities — how (LEKA-366): its level, how critical,
    where in its life; a process's type and step; the data its source names,
    as named (enrichment finds them)."""

    level: int | None = None
    criticality: str | None = None
    criticality_raw: str | None = None
    stage: str | None = None
    stage_raw: str | None = None
    process_type: str | None = None
    step: int | None = None
    data_names: list[str] | None = None


# A kind's schema: named here, as `type` inside EntityKind is its field.
Schema = type[Attributes]


@dataclass(frozen=True)
class EntityKind:
    type: EntityType
    version: int
    # How the company is read: organisation, applications, delivery,
    # operations, infrastructure, data, knowledge, business.
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
        EntityKind(EntityType.ISSUE, 2, "delivery", WorkAttributes, ("issue",)),
        EntityKind(EntityType.PULL_REQUEST, 2, "delivery", WorkAttributes, ("pull_request",)),
        EntityKind(EntityType.COMMIT, 1, "delivery", CommitAttributes, ("commit",)),
        EntityKind(EntityType.RELEASE, 2, "delivery", ReleaseAttributes, ("release",)),
        EntityKind(EntityType.DEPLOYMENT, 2, "delivery", DeploymentAttributes, ("deployment",)),
        EntityKind(EntityType.INCIDENT, 2, "operations", IncidentAttributes, ("incident",)),
        EntityKind(EntityType.CHANGE, 1, "operations", ChangeAttributes, ("change",)),
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
        EntityKind(EntityType.DOCUMENT, 2, "knowledge", DocumentAttributes, ("document",)),
        EntityKind(
            EntityType.KNOWLEDGE_SPACE,
            1,
            "knowledge",
            KnowledgeSpaceAttributes,
            ("knowledge_space",),
        ),
        EntityKind(
            EntityType.BUSINESS_CAPABILITY,
            1,
            "business",
            BusinessAttributes,
            ("business_capability",),
        ),
        EntityKind(
            EntityType.BUSINESS_PROCESS, 1, "business", BusinessAttributes, ("business_process",)
        ),
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
    """A kind of relationship and its contract (LEKA-368): what it means,
    read from → to; the kinds of entities each end may be; whether a thing
    has one only, whether a loop of it is a contradiction, whether it says
    what a thing needs to work. A build drops a relationship whose ends
    break the contract and says why (contracts.py)."""

    type: RelationshipType
    version: int
    # The relationships of enrichment (docs/enrichment.md) it is built from.
    built_from: tuple[str, ...]
    meaning: str = ""
    # The kinds its ends may be: None, any.
    sources: frozenset[EntityType] | None = None
    targets: frozenset[EntityType] | None = None
    # One a thing: a person's manager, a ticket's parent — more is said.
    single: bool = False
    # A loop is a contradiction — what holds what, who reports to whom: an
    # inferred link closing one is dropped; stated ones are said.
    acyclic: bool = False
    # What a thing needs to work: a loop of it is said; the dependency walk
    # may follow it.
    dependency: bool = False


E = EntityType
# What holds things: what `part_of` points at (LEKA-361 → LEKA-367).
HOLDERS = frozenset(
    {
        E.REPOSITORY,
        E.PROJECT,
        E.SERVICE,
        E.APPLICATION,
        E.CLOUD_ACCOUNT,
        E.RESOURCE_GROUP,
        E.INFRA_RESOURCE,
        E.DATABASE,
        E.SCHEMA,
        E.KNOWLEDGE_SPACE,
        E.BUSINESS_PROCESS,
    }
)
PEOPLE = frozenset({E.PERSON})
TICKETS = frozenset({E.ISSUE, E.INCIDENT, E.CHANGE})
RUNNING = frozenset({E.SERVICE, E.APPLICATION, E.INFRA_RESOURCE, E.DATABASE})
TOUCHED = RUNNING | {E.DATA_OBJECT, E.REPOSITORY}
BUSINESS = frozenset({E.BUSINESS_CAPABILITY, E.BUSINESS_PROCESS})
DATA = frozenset({E.DATA_OBJECT, E.SCHEMA, E.DATABASE})
AREAS = frozenset({E.REPOSITORY, E.PROJECT, E.SERVICE, E.KNOWLEDGE_SPACE})
SHIPPED = frozenset({E.COMMIT, E.RELEASE})
CAUSES = TICKETS | {E.DEPLOYMENT, E.PULL_REQUEST, E.COMMIT, E.RELEASE}
R = RelationshipType

RELATIONSHIP_KINDS: dict[RelationshipType, RelationshipKind] = {
    kind.type: kind
    for kind in (
        RelationshipKind(R.PART_OF, 2, ("part_of",), "is part of", targets=HOLDERS, acyclic=True),
        RelationshipKind(
            R.CHILD_OF,
            2,
            ("child_of",),
            "is a child of",
            sources=TICKETS | {E.DOCUMENT, E.TEAM, E.BUSINESS_CAPABILITY},
            targets=TICKETS | {E.DOCUMENT, E.TEAM, E.BUSINESS_CAPABILITY},
            single=True,
            acyclic=True,
        ),
        RelationshipKind(
            R.DEPENDS_ON,
            2,
            ("depends_on",),
            "depends on",
            sources=RUNNING,
            targets=RUNNING,
            dependency=True,
        ),
        RelationshipKind(
            R.OWNED_BY, 2, ("owned_by",), "is owned by", targets=frozenset({E.TEAM, E.PERSON})
        ),
        RelationshipKind(
            R.MAINTAINED_BY,
            2,
            ("maintained_by",),
            "is maintained by",
            sources=AREAS | {E.APPLICATION},
            targets=PEOPLE,
        ),
        RelationshipKind(
            R.MEMBER_OF,
            2,
            ("member_of",),
            "is a member of",
            sources=PEOPLE,
            targets=frozenset({E.TEAM}),
        ),
        RelationshipKind(
            R.AUTHORED_BY, 2, ("authored_by", "committed_by"), "is authored by", targets=PEOPLE
        ),
        RelationshipKind(R.ASSIGNED_TO, 2, ("assigned_to",), "is assigned to", targets=PEOPLE),
        RelationshipKind(R.REVIEWED_BY, 2, ("reviewed_by",), "is reviewed by", targets=PEOPLE),
        RelationshipKind(
            R.REPORTED_BY, 2, ("reported_by", "created_by"), "is reported by", targets=PEOPLE
        ),
        RelationshipKind(R.LED_BY, 2, ("led_by",), "is led by", targets=PEOPLE),
        RelationshipKind(
            R.AFFECTS,
            2,
            ("affects",),
            "affects",
            sources=frozenset({E.INCIDENT, E.CHANGE}),
            targets=TOUCHED,
        ),
        RelationshipKind(
            R.RESOLVES,
            2,
            ("resolves",),
            "resolves",
            sources=frozenset({E.PULL_REQUEST, E.COMMIT, E.ISSUE}),
            targets=TICKETS,
        ),
        RelationshipKind(
            R.IMPLEMENTS,
            2,
            ("implements",),
            "implements",
            sources=frozenset({E.PULL_REQUEST, E.COMMIT, E.ISSUE}),
            targets=TICKETS,
        ),
        RelationshipKind(
            R.MERGES,
            2,
            ("merges",),
            "merges",
            sources=frozenset({E.COMMIT, E.PULL_REQUEST}),
            targets=frozenset({E.PULL_REQUEST, E.COMMIT}),
        ),
        RelationshipKind(R.MENTIONS, 2, ("mentions",), "mentions"),
        RelationshipKind(
            R.IN_NETWORK,
            2,
            ("in_network",),
            "is in the network",
            sources=frozenset({E.INFRA_RESOURCE, E.DATABASE}),
            targets=frozenset({E.INFRA_RESOURCE}),
        ),
        RelationshipKind(R.RUNS_IN, 2, ("runs_in",), "runs in", targets=frozenset({E.ENVIRONMENT})),
        RelationshipKind(
            R.REFERENCES,
            2,
            ("references",),
            "references",
            sources=frozenset({E.DATA_OBJECT, E.DOCUMENT}),
            targets=frozenset({E.DATA_OBJECT, E.DOCUMENT, E.KNOWLEDGE_SPACE}),
            dependency=True,
        ),
        RelationshipKind(
            R.READS_FROM,
            2,
            ("reads_from",),
            "reads from",
            sources=frozenset({E.DATA_OBJECT}),
            targets=frozenset({E.DATA_OBJECT}),
            dependency=True,
        ),
        RelationshipKind(
            R.REPORTS_TO,
            2,
            ("reports_to",),
            "reports to",
            sources=PEOPLE,
            targets=PEOPLE,
            single=True,
            acyclic=True,
        ),
        RelationshipKind(
            R.CONTRIBUTES_TO,
            2,
            ("contributes_to",),
            "contributes to",
            sources=PEOPLE,
            targets=AREAS,
        ),
        RelationshipKind(
            R.DESCRIBES,
            2,
            ("describes",),
            "describes",
            sources=frozenset({E.DOCUMENT, E.KNOWLEDGE_SPACE}),
        ),
        RelationshipKind(
            R.EDITED_BY,
            2,
            ("edited_by",),
            "is edited by",
            sources=frozenset({E.DOCUMENT}),
            targets=PEOPLE,
        ),
        RelationshipKind(
            R.SUPPORTED_BY,
            2,
            ("supported_by",),
            "is supported by",
            sources=BUSINESS,
            targets=frozenset({E.APPLICATION, E.SERVICE}),
            dependency=True,
        ),
        RelationshipKind(
            R.USES, 2, ("uses",), "uses", sources=BUSINESS, targets=DATA, dependency=True
        ),
        RelationshipKind(
            R.REALIZES,
            2,
            ("realizes",),
            "realizes",
            sources=frozenset({E.BUSINESS_PROCESS}),
            targets=frozenset({E.BUSINESS_CAPABILITY}),
        ),
        # What shipped what, where; what caused an incident (LEKA-367).
        RelationshipKind(
            R.DEPLOYS,
            2,
            ("deploys",),
            "deploys",
            sources=frozenset({E.DEPLOYMENT}),
            targets=SHIPPED,
        ),
        RelationshipKind(
            R.DEPLOYED_TO,
            2,
            ("deployed_to",),
            "is deployed to",
            sources=frozenset({E.DEPLOYMENT}),
            targets=frozenset({E.ENVIRONMENT, E.INFRA_RESOURCE, E.DATABASE}),
        ),
        RelationshipKind(
            R.CAUSED_BY,
            2,
            ("caused_by",),
            "is caused by",
            sources=TICKETS,
            targets=CAUSES,
        ),
        RelationshipKind(R.OWNS, 2, (), "owns"),
    )
}
# What a dependency walk may follow (LEKA-368).
DEPENDENCIES = tuple(kind.type for kind in RELATIONSHIP_KINDS.values() if kind.dependency)

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
