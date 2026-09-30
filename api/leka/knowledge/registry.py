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
MODEL_VERSION = 1


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


class ServiceAttributes(Attributes):
    environment: str | None = None
    tier: str | None = None
    incidents_90d: int | None = None
    open_incidents: int | None = None
    mttr_minutes: int | None = None


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


class ResourceAttributes(Attributes):
    """Cloud resources and databases."""

    resource_kind: str | None = None
    environment: str | None = None
    exposure: str | None = None
    region: str | None = None
    tags: dict[str, object] | None = None


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
        EntityKind(EntityType.PERSON, 1, "organisation", Attributes, ("person",)),
        EntityKind(EntityType.TEAM, 1, "organisation", Attributes, ("team",)),
        EntityKind(EntityType.SERVICE, 1, "applications", ServiceAttributes, ("service",)),
        EntityKind(EntityType.REPOSITORY, 1, "applications", RepositoryAttributes, ("repository",)),
        EntityKind(EntityType.PROJECT, 1, "delivery", Attributes, ("project",)),
        EntityKind(EntityType.ISSUE, 1, "delivery", WorkAttributes, ("issue",)),
        EntityKind(EntityType.PULL_REQUEST, 1, "delivery", WorkAttributes, ("pull_request",)),
        EntityKind(EntityType.COMMIT, 1, "delivery", CommitAttributes, ("commit",)),
        EntityKind(EntityType.RELEASE, 1, "delivery", Attributes, ("release",)),
        EntityKind(EntityType.DEPLOYMENT, 1, "delivery", Attributes, ("deployment",)),
        EntityKind(EntityType.INCIDENT, 1, "operations", IncidentAttributes, ("incident",)),
        EntityKind(
            EntityType.INFRA_RESOURCE, 1, "infrastructure", ResourceAttributes, ("infra_resource",)
        ),
        EntityKind(EntityType.DATABASE, 1, "infrastructure", ResourceAttributes, ("database",)),
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
