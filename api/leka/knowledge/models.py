"""The graph: two generic tables, not one table per kind of object.

A table per object type would mean a migration, a model and a repository for
every new thing a connector learns to see. Instead every object is an Entity
discriminated by `type`, with its specifics in `attributes` (JSONB), and
every link is a Relationship. Adding "kubernetes cluster" becomes a new enum
value, not a new table.

The cost is that the database cannot validate what lives inside attributes.
That validation belongs to the normalisation step in leka.ingestion, and to
the Pydantic schemas in this module. See docs/adr/003-entity-model.md.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKeyConstraint,
    Index,
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
    """What an entity is.

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


class RelationshipType(enum.StrEnum):
    """How two entities relate. Direction matters: from -> to."""

    DEPENDS_ON = "depends_on"
    OWNS = "owns"
    DEPLOYED_TO = "deployed_to"
    MENTIONS = "mentions"
    CAUSED_BY = "caused_by"
    MEMBER_OF = "member_of"


class Entity(Base, WorkspaceScopedMixin):
    """One object in a customer's information system."""

    __tablename__ = "entities"
    __table_args__ = (
        # Identity of an entity: the same object seen twice by the same source
        # is one row, updated. This is what makes the background loop
        # idempotent — a re-sync must not double the graph.
        UniqueConstraint(
            "workspace_id", "source_id", "external_id", name="uq_entities_workspace_source_external"
        ),
        # Target for the composite foreign keys in relationships.
        UniqueConstraint("workspace_id", "id", name="uq_entities_workspace_id_id"),
        # An entity's source must belong to the SAME workspace. A plain
        # source_id foreign key would happily accept another tenant's source;
        # this composite key makes that row impossible to write.
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_entities_workspace_source",
            ondelete="CASCADE",
        ),
        Index("ix_entities_workspace_type", "workspace_id", "type"),
        # Queries filter on attributes -> GIN, not btree.
        Index("ix_entities_attributes", "attributes", postgresql_using="gin"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    type: Mapped[EntityType] = mapped_column(
        Enum(
            EntityType,
            name="type",
            native_enum=False,
            length=50,
            values_callable=_values,
        ),
        nullable=False,
    )
    # The identifier the source itself uses: a GitHub node id, a Jira key, an
    # ARN. Opaque to LEKA, stable across syncs.
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)

    attributes: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # How sure the background loop is that this entity is real and current.
    # An answer built on low-confidence entities says so.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")

    # Last time a sync saw it. Silence is evidence: an entity nobody has seen
    # for weeks is probably gone.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_relationships_workspace_source",
            ondelete="CASCADE",
        ),
        # The graph is walked in both directions — "what does payment-api
        # depend on" and "who depends on payment-api" are both everyday
        # questions, so both get an index.
        Index("ix_relationships_from", "workspace_id", "from_entity_id", "type"),
        Index("ix_relationships_to", "workspace_id", "to_entity_id", "type"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
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
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
