"""Types the knowledge module exposes: the company model as it is read.

The per-type validation of `attributes` is the registry's (registry.py):
the database cannot check what is inside a JSONB column —
docs/adr/003-entity-model.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime

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
