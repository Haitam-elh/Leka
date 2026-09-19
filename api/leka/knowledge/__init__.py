"""Knowledge: the entity graph and everything that reads or writes it.

The source of truth about a customer's architecture. Filled by the background
loop, read by the interactive one.

May depend on leka.ingestion and below. Must not import leka.context or
leka.intentions (architecture rule 1).
"""

from leka.knowledge.models import Entity, EntityType, Relationship, RelationshipType
from leka.knowledge.repository import EntityRepository, RelationshipRepository
from leka.knowledge.schemas import EntityRead, Neighbourhood, RelationshipRead
from leka.knowledge.service import KnowledgeService

__all__ = [
    "Entity",
    "EntityRead",
    "EntityRepository",
    "EntityType",
    "KnowledgeService",
    "Neighbourhood",
    "Relationship",
    "RelationshipRead",
    "RelationshipRepository",
    "RelationshipType",
]
