"""Business logic over the company model.

What leka.context and leka.intentions ask of the graph: an entity, its
neighbourhood, its history. The registry (registry.py) is what they read to
know what kinds of things a company is made of.

Depends on leka.ingestion. Must not import leka.context or leka.intentions
(architecture rule 1).
"""

from __future__ import annotations

import uuid

from leka.knowledge.repository import EntityRepository
from leka.knowledge.schemas import EntityRead, Neighbourhood, RelationshipRead

MAX_DEPTH = 3
MAX_ENTITIES = 200


class KnowledgeService:
    """Reads the company model for the modules that answer questions."""

    def __init__(self, entities: EntityRepository) -> None:
        self._entities = entities

    async def neighbourhood(
        self, entity_id: uuid.UUID, *, depth: int = 1, limit: int = MAX_ENTITIES
    ) -> Neighbourhood | None:
        """An entity and what surrounds it, `depth` steps away (at most
        three) — None when the workspace has no such entity."""
        found, edges = await self._entities.neighbourhood(
            entity_id, depth=min(max(depth, 1), MAX_DEPTH), limit=min(limit, MAX_ENTITIES)
        )
        root = next((entity for entity in found if entity.id == entity_id), None)
        if root is None:
            return None
        return Neighbourhood(
            root=EntityRead.model_validate(root),
            entities=[EntityRead.model_validate(e) for e in found if e.id != entity_id],
            relationships=[RelationshipRead.model_validate(r) for r in edges],
        )
