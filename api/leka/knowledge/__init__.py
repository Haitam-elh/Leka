"""Knowledge: the company model (LEKA-361) and everything that reads it.

The source of truth about a customer's company — its services,
repositories, people, teams, infrastructure — as entity resolution and
enrichment made it of the sources: typed, versioned, with a lifecycle and
where every piece came from. Built by the background loop, read by the
interactive one.

May depend on leka.ingestion and below. Must not import leka.context or
leka.intentions (architecture rule 1).
"""

from leka.knowledge.models import (
    Entity,
    EntityType,
    EntityVersion,
    Lifecycle,
    ModelRun,
    Relationship,
    RelationshipType,
)
from leka.knowledge.registry import ENTITY_KINDS, MODEL_VERSION, RELATIONSHIP_KINDS
from leka.knowledge.repository import EntityRepository, ModelRepository
from leka.knowledge.schemas import (
    EntityBrief,
    EntityDetail,
    EntityKindRead,
    EntityRead,
    EntityVersionRead,
    LinkRead,
    ModelRunRead,
    ModelStatus,
    Neighbourhood,
    Registry,
    RelationshipKindRead,
    RelationshipRead,
)
from leka.knowledge.service import KnowledgeService

__all__ = [
    "ENTITY_KINDS",
    "MODEL_VERSION",
    "RELATIONSHIP_KINDS",
    "Entity",
    "EntityBrief",
    "EntityDetail",
    "EntityKindRead",
    "EntityRead",
    "EntityRepository",
    "EntityType",
    "EntityVersion",
    "EntityVersionRead",
    "KnowledgeService",
    "Lifecycle",
    "LinkRead",
    "ModelRepository",
    "ModelRun",
    "ModelRunRead",
    "ModelStatus",
    "Neighbourhood",
    "Registry",
    "Relationship",
    "RelationshipKindRead",
    "RelationshipRead",
    "RelationshipType",
]
