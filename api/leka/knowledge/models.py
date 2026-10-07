"""The company model (LEKA-361): two generic tables — and the history of both.

A table per object type would mean a migration, a model and a repository for
every new thing a connector learns to see. Instead every object is an Entity
discriminated by `type`, with its specifics in `attributes` (JSONB), and
every link is a Relationship. Adding "kubernetes cluster" is a new type in
the registry (registry.py), not a new table. See docs/adr/003-entity-model.md
and docs/company-model.md.

WHAT AN ENTITY IS. One real thing of the customer's company — a service, a
repository, a person — as entity resolution found it across the sources
(LEKA-357) and enrichment completed it (LEKA-359). Its id IS the resolved
entity's: stable from one build to the next. It keeps where every piece of
it came from (`provenance`), a LIFECYCLE (active, dormant, archived, removed
— a thing gone from every source is removed, not deleted: its history
stays), and a VERSION, raised each time what it says changes; every version
is kept in `entity_versions`.

The database cannot validate what lives inside attributes: the registry's
schema per type does, before a row is written.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin

# An entity's words, for search (LEKA-369): 'simple', no stemming — names are
# not prose, and the company speaks French and English. Written as
# PostgreSQL reads it back, so that `alembic check` sees no difference.
SEARCH_VECTOR = (
    "(setweight(to_tsvector('simple'::regconfig, search_name), 'A'::\"char\") || "
    "setweight(to_tsvector('simple'::regconfig, search_text), 'B'::\"char\"))"
)


def _values(enum_class: type[enum.StrEnum]) -> list[str]:
    """Store the enum VALUE in PostgreSQL, not the member name."""
    return [member.value for member in enum_class]


class EntityType(enum.StrEnum):
    """What an entity is. Each is described — its version, its category, its
    attributes — in registry.py.

    Stored as text with a CHECK constraint rather than a PostgreSQL ENUM.
    An ENUM cannot drop a value — PostgreSQL has no DROP VALUE — and a
    migration that adds one cannot use it in the same transaction. Every new
    connector would add types, so that cost lands on us repeatedly. A CHECK
    constraint is dropped and recreated in one ordinary, transactional
    statement. See docs/adr/006-enum-storage.md.
    """

    SERVICE = "service"
    REPOSITORY = "repository"
    INCIDENT = "incident"
    DEPLOYMENT = "deployment"
    PERSON = "person"
    DOCUMENT = "document"
    INFRA_RESOURCE = "infra_resource"
    DATABASE = "database"
    TEAM = "team"
    PROJECT = "project"
    ISSUE = "issue"
    PULL_REQUEST = "pull_request"
    COMMIT = "commit"
    RELEASE = "release"
    APPLICATION = "application"
    ENVIRONMENT = "environment"
    # What resources are in (LEKA-363): an AWS account, an Azure
    # subscription, a Google Cloud project — and an Azure resource group.
    CLOUD_ACCOUNT = "cloud_account"
    RESOURCE_GROUP = "resource_group"
    # A database's schemas, and what holds its data — a table, a view, a
    # collection (LEKA-364).
    SCHEMA = "schema"
    DATA_OBJECT = "data_object"
    # Where documents are kept — a Confluence space, a Notion database, a
    # Slab topic, a Guru collection, a shared drive, a SharePoint library —
    # and what the business is made of: what it does, how (LEKA-366).
    KNOWLEDGE_SPACE = "knowledge_space"
    BUSINESS_CAPABILITY = "business_capability"
    BUSINESS_PROCESS = "business_process"
    # Something changed in the company's systems: a change request, a
    # configuration change, a change event (LEKA-367).
    CHANGE = "change"


class RelationshipType(enum.StrEnum):
    """How two entities relate. Direction matters: from -> to."""

    DEPENDS_ON = "depends_on"
    OWNS = "owns"
    DEPLOYED_TO = "deployed_to"
    MENTIONS = "mentions"
    CAUSED_BY = "caused_by"
    MEMBER_OF = "member_of"
    PART_OF = "part_of"
    OWNED_BY = "owned_by"
    MAINTAINED_BY = "maintained_by"
    AUTHORED_BY = "authored_by"
    ASSIGNED_TO = "assigned_to"
    REVIEWED_BY = "reviewed_by"
    REPORTED_BY = "reported_by"
    LED_BY = "led_by"
    AFFECTS = "affects"
    RESOLVES = "resolves"
    IMPLEMENTS = "implements"
    MERGES = "merges"
    CHILD_OF = "child_of"
    IN_NETWORK = "in_network"
    RUNS_IN = "runs_in"
    # A table's foreign key, to the table it references; a view, to what it
    # reads from (LEKA-364).
    REFERENCES = "references"
    READS_FROM = "reads_from"
    # A person, to who they report; a person, to what they work on — their
    # expertise, as their work shows it (LEKA-365).
    REPORTS_TO = "reports_to"
    CONTRIBUTES_TO = "contributes_to"
    # A document, to what it is about; to who last edited it. A business
    # capability or process, to the applications and services supporting
    # it, to the data it uses; a process, to the capability it realizes
    # (LEKA-366).
    DESCRIBES = "describes"
    EDITED_BY = "edited_by"
    SUPPORTED_BY = "supported_by"
    USES = "uses"
    REALIZES = "realizes"
    # A deployment, to the commit or the release it ships (LEKA-367).
    DEPLOYS = "deploys"


class Lifecycle(enum.StrEnum):
    """Where a thing is in its life, as the sources show it."""

    # Seen, and something moved around it lately.
    ACTIVE = "active"
    # Still there, nothing done to it for 180 days (enrichment's lifecycle).
    DORMANT = "dormant"
    # Its source says so: an archived repository, a deleted document, a
    # terminated instance, a deleted subscription.
    ARCHIVED = "archived"
    # Gone from every source: kept, with its history, never shown as current.
    REMOVED = "removed"


class Entity(Base, WorkspaceScopedMixin):
    """One real thing of a customer's company."""

    __tablename__ = "entities"
    __table_args__ = (
        # Target for the composite foreign keys in relationships and versions.
        UniqueConstraint("workspace_id", "id", name="uq_entities_workspace_id_id"),
        Index("ix_entities_workspace_type", "workspace_id", "type"),
        Index("ix_entities_workspace_type_name", "workspace_id", "type", "name"),
        Index("ix_entities_workspace_key", "workspace_id", "key"),
        # Incidents, changes, deployments in time order (LEKA-367).
        Index("ix_entities_workspace_type_occurred", "workspace_id", "type", "occurred_at"),
        # Queries filter on attributes -> GIN, not btree.
        Index("ix_entities_attributes", "attributes", postgresql_using="gin"),
        # Search: the words of its names and of what says what it is (LEKA-369).
        Index("ix_entities_search", "search_vector", postgresql_using="gin"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "lifecycle IN ('active', 'dormant', 'archived', 'removed')", name="lifecycle"
        ),
        CheckConstraint("(lifecycle = 'removed') = (removed_at IS NOT NULL)", name="removed_when"),
    )

    type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="type", native_enum=False, length=50, values_callable=_values),
        nullable=False,
    )
    # The key that says it best (docs/resolution.md): `github.com/acme/api`,
    # `person:email:sara@acme.io`, `service:billing`.
    key: Mapped[str] = mapped_column(String(1000), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    # What it is — its sources' word, then enrichment's where they said
    # nothing — checked against its type's schema.
    attributes: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    lifecycle: Mapped[Lifecycle] = mapped_column(
        Enum(Lifecycle, name="lifecycle", native_enum=False, length=20, values_callable=_values),
        nullable=False,
        server_default=Lifecycle.ACTIVE.value,
    )
    # Raised each time what it says changes; every version is kept.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # The version of its type's schema it was checked against.
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # What it says, hashed: how a build knows it changed.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    # How sure the merges that made it are, and the best quality of its
    # records (validation, LEKA-358).
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Where it came from: every source and key it goes by, and the origin of
    # each attribute — a source, or an enrichment rule and its confidence.
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last time a source showed it. Silence is evidence.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifecycle_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When it happened, by its sources' dates — an incident opened, a
    # deployment done, a change made, a release published, a pull request
    # merged; none for what is not an event (LEKA-367).
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # What search reads (search.py, LEKA-369): its names, and what else says
    # what it is — folded, written at each build — and their words, indexed:
    # the names weigh more.
    search_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    search_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_VECTOR, persisted=True),
        nullable=False,
    )


class Relationship(Base, WorkspaceScopedMixin):
    """A directed edge between two entities of the same workspace."""

    __tablename__ = "relationships"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "from_entity_id",
            "to_entity_id",
            "type",
            name="uq_relationships_edge",
        ),
        # Both ends are pinned to this row's workspace, so an edge can never
        # join two tenants' graphs.
        ForeignKeyConstraint(
            ["workspace_id", "from_entity_id"],
            ["entities.workspace_id", "entities.id"],
            name="fk_relationships_workspace_from_entity",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "to_entity_id"],
            ["entities.workspace_id", "entities.id"],
            name="fk_relationships_workspace_to_entity",
            ondelete="CASCADE",
        ),
        # The graph is walked in both directions — "what does payment-api
        # depend on" and "who depends on payment-api" are both everyday
        # questions, so both get an index.
        Index("ix_relationships_from", "workspace_id", "from_entity_id", "type"),
        Index("ix_relationships_to", "workspace_id", "to_entity_id", "type"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("origin IN ('stated', 'inferred', 'accepted')", name="origin"),
    )

    from_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[RelationshipType] = mapped_column(
        Enum(
            RelationshipType,
            name="type",
            native_enum=False,
            length=50,
            values_callable=_values,
        ),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    # Stated by a source, inferred by an enrichment rule (`rule`) — or
    # accepted: proposed by LEKA's enrichment and validated (LEKA-380).
    origin: Mapped[str] = mapped_column(String(10), nullable=False, server_default="stated")
    rule: Mapped[str] = mapped_column(String(100), nullable=False, server_default="stated")
    cross_source: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # What holds of it beyond its ends: `environments`, the ones it is true
    # in — a service's production database is not its staging one
    # (LEKA-362). Empty: everywhere, or unknown.
    attributes: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # The records that stated it, or what it was inferred from.
    provenance: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # Its life (LEKA-368): the first build it was in, the last that changed
    # it — its origin, rule, environments, its confidence by 0.05 at least.
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RelationshipChange(Base, WorkspaceScopedMixin):
    """A relationship that appeared, changed or went, at a build (LEKA-368):
    the relationships' history, append-only. Its ends are ids — an entity is
    never deleted, a removed one is kept."""

    __tablename__ = "relationship_changes"
    __table_args__ = (
        CheckConstraint("change IN ('added', 'changed', 'removed')", name="change"),
        Index("ix_relationship_changes_workspace_recorded", "workspace_id", "recorded_at"),
        Index("ix_relationship_changes_from", "workspace_id", "from_entity_id"),
        Index("ix_relationship_changes_to", "workspace_id", "to_entity_id"),
    )

    from_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    change: Mapped[str] = mapped_column(String(10), nullable=False)
    # {confidence, origin, rule, environments} before and after; none for
    # what was not there.
    before: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True
    )


class RelationshipIssue(Base, WorkspaceScopedMixin):
    """What the last build found wrong with a relationship (LEKA-368): an
    end its contract does not take — dropped — a loop where none may be, more
    than one of what a thing has one of. Made again at each build."""

    __tablename__ = "relationship_issues"
    __table_args__ = (
        CheckConstraint("severity IN ('error', 'warning')", name="severity"),
        Index("ix_relationship_issues_workspace_type", "workspace_id", "type"),
    )

    from_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    issue: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    rule: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True
    )


class EntityVersion(Base, WorkspaceScopedMixin):
    """What an entity said, at one of its versions — its history."""

    __tablename__ = "entity_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["entities.workspace_id", "entities.id"],
            name="fk_entity_versions_workspace_entity",
            ondelete="CASCADE",
        ),
        UniqueConstraint("entity_id", "version", name="uq_entity_versions_entity_version"),
        # What changed over time, workspace-wide (LEKA-383).
        Index("ix_entity_versions_workspace_recorded", "workspace_id", "recorded_at"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # {name, attributes, lifecycle} as they were.
    content: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    # What changed from the version before: "name", "lifecycle", attributes.
    changed: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The build that recorded it. Single-column: SET NULL through
    # workspace_id would null the workspace too.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True
    )


class ModelRun(Base, WorkspaceScopedMixin):
    """One build of a workspace's company model: from which enrichment run,
    by which model version, what it did — or the error it stopped on."""

    __tablename__ = "model_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed', 'abandoned')", name="status"),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"
        ),
        Index("ix_model_runs_workspace_started_at", "workspace_id", "started_at"),
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The enrichment run it read (LEKA-359). No foreign key: that history is
    # pruned, and this says what it was made from, not a link to follow.
    enrichment_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The validated facts it applied (LEKA-380), as one fingerprint: a fact
    # accepted or withdrawn since is something new to build.
    assertions: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counts: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)


ASSERTION_KINDS = ("attribute", "relationship", "absence")


class ModelAssertion(Base, WorkspaceScopedMixin):
    """A fact about the company model that LEKA's enrichment proposed and
    that was validated — by a person, or by the workspace's policy
    (LEKA-380). Each build applies it beside what the sources say: an
    attribute where no source says one — or, when it `overrides`, instead
    of what a source says, only because someone said so — a relationship
    with the origin `accepted` — or, an `absence` (LEKA-382), a relationship
    someone refuted, which the build leaves out whoever states it.

    Its id is the enrichment candidate's (leka.intelligence) — or, for a
    dispute someone settled, one per fact the decision makes, the conflict
    named in `provenance.conflict_id` (LEKA-382). The intelligence keeps
    the proposal, its evidence and the decision. A fact withdrawn is
    deleted here: the next build no longer applies it, and what the
    sources say comes back. No foreign key to the entities: one that goes
    leaves a fact the build skips, not an error."""

    __tablename__ = "model_assertions"
    __table_args__ = (
        CheckConstraint("kind IN ('attribute', 'relationship', 'absence')", name="kind"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "(kind = 'attribute') = (entity_id IS NOT NULL AND attribute IS NOT NULL)",
            name="attribute_said",
        ),
        CheckConstraint(
            "(kind IN ('relationship', 'absence')) = (from_entity_id IS NOT NULL "
            "AND to_entity_id IS NOT NULL AND relationship_type IS NOT NULL)",
            name="relationship_said",
        ),
    )

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # An attribute: of which entity, which, the value.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attribute: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    overrides: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # A relationship: its ends and its kind.
    from_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    to_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    relationship_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # The analysis that proposed it, as the model's `rule` says it.
    rule: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Who validated it and how: {candidate_id, analyzer, decided_via,
    # decided_by, decided_at}.
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )


OPERATION_KINDS = ("restore", "rebuild")
OPERATION_STATUSES = ("queued", "applied", "done", "failed", "undone")


class ModelSnapshot(Base, WorkspaceScopedMixin):
    """What the company model held at one moment (LEKA-383): how many of each
    kind, in each lifecycle, how many relationships of each kind, and how
    well each kind is known — what its course over time is drawn from.
    Written by a build that changed something, or the first of a day; kept
    SNAPSHOT_DAYS, the latest always."""

    __tablename__ = "model_snapshots"
    __table_args__ = (Index("ix_model_snapshots_workspace_built", "workspace_id", "built_at"),)

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True
    )
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Rebuilt from the history (entity_versions, relationship_changes) rather
    # than written by a build: what the history says, without what it does
    # not keep — how many sources said each thing.
    reconstructed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # {types: {type: n}, lifecycles: {state: n}, relationships: {type: n}}
    counts: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # {type: {total, owned, documented, corroborated, connected}}: the
    # coverage of each kind (GET /knowledge/coverage), then.
    measures: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class ModelOperation(Base, WorkspaceScopedMixin):
    """A controlled change to the model's course (LEKA-383), asked by someone
    and kept: who, when, why, what came of it.

    restore   an entity's attributes put back as one of its versions said
              them: validated facts (model_assertions, provenance
              `operation_id`) the next build applies — `applied`, then
              `undone` when someone takes it back
    rebuild   the model built again from what it is made of, though nothing
              new came: `queued`, then `done` with the run that did it —
              or `failed`, and why"""

    __tablename__ = "model_operations"
    __table_args__ = (
        CheckConstraint("kind IN ('restore', 'rebuild')", name="kind"),
        CheckConstraint(
            "status IN ('queued', 'applied', 'done', 'failed', 'undone')",
            name="status",
        ),
        Index("ix_model_operations_workspace_created", "workspace_id", "created_at"),
    )

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entity_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A restore: {attributes: {name: {before, after}}} — what the model
    # said, what it says again. A rebuild: what the build did (its counts),
    # or its error.
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    undone_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
