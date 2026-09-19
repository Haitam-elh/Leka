"""Types the knowledge module exposes.

Also where the per-type validation of `attributes` belongs. The database
cannot check what is inside a JSONB column — that cost is stated plainly in
docs/adr/003-entity-model.md — so a Pydantic model per entity type is what
keeps the graph from filling with typos.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from leka.knowledge.models import EntityType, RelationshipType


class EntityRead(BaseModel):
    """An entity as it leaves the module."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    type: EntityType
    external_id: str
    source_id: uuid.UUID
    name: str
    attributes: dict[str, object]
    confidence: float
    last_seen_at: datetime | None


class RelationshipRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    type: RelationshipType
    confidence: float
    source_id: uuid.UUID


class Neighbourhood(BaseModel):
    """One entity and what surrounds it.

    The unit leka.context asks for. Returning a subgraph rather than a list
    of rows keeps traversal knowledge inside this module.
    """

    model_config = ConfigDict(frozen=True)

    root: EntityRead
    entities: list[EntityRead] = Field(default_factory=list)
    relationships: list[RelationshipRead] = Field(default_factory=list)
