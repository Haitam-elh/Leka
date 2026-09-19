"""Business logic over the graph.

Owns the questions that are about the graph itself: is this candidate the
same thing as that existing entity, does this edge still hold, how confident
are we in what we are about to assert.

Depends on leka.ingestion. Must not import leka.context or leka.intentions
(architecture rule 1).
"""

from __future__ import annotations

from leka.knowledge.repository import EntityRepository, RelationshipRepository


class KnowledgeService:
    """Maintains the entity graph."""

    def __init__(
        self,
        entities: EntityRepository,
        relationships: RelationshipRepository,
    ) -> None:
        self._entities = entities
        self._relationships = relationships
