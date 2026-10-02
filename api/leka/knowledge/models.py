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
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin


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
        CheckConstraint("origin IN ('stated', 'inferred')", name="origin"),
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
    # Stated by a source, or inferred by an enrichment rule (`rule`).
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
    counts: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
