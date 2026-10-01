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
from leka.knowledge.repository import (
    DataFilters,
    EntityRepository,
    InfrastructureFilters,
    LandscapeFilters,
    ModelRepository,
)
from leka.knowledge.schemas import (
    CloudAccountDetail,
    CloudAccountRead,
    Criticality,
    DatabaseDetail,
    DatabaseRead,
    DataObjectDetail,
    DataObjectRead,
    Dependencies,
    DependencyNode,
    DependencyRead,
    EntityBrief,
    EntityDetail,
    EntityKindRead,
    EntityRead,
    EntityVersionRead,
    InfrastructureDetail,
    InfrastructureRead,
    LandscapeDetail,
    LandscapeRead,
    LinkRead,
    ModelRunRead,
    ModelStatus,
    Neighbourhood,
    PartRead,
    Registry,
    RelationshipKindRead,
    RelationshipRead,
    ResourceEnvironment,
)
from leka.knowledge.service import KnowledgeService

__all__ = [
    "ENTITY_KINDS",
    "MODEL_VERSION",
    "RELATIONSHIP_KINDS",
    "CloudAccountDetail",
    "CloudAccountRead",
    "Criticality",
    "DataFilters",
    "DataObjectDetail",
    "DataObjectRead",
    "DatabaseDetail",
    "DatabaseRead",
    "Dependencies",
    "DependencyNode",
    "DependencyRead",
    "Entity",
    "EntityBrief",
    "EntityDetail",
    "EntityKindRead",
    "EntityRead",
    "EntityRepository",
    "EntityType",
    "EntityVersion",
    "EntityVersionRead",
    "InfrastructureDetail",
    "InfrastructureFilters",
    "InfrastructureRead",
    "KnowledgeService",
    "LandscapeDetail",
    "LandscapeFilters",
    "LandscapeRead",
    "Lifecycle",
    "LinkRead",
    "ModelRepository",
    "ModelRun",
    "ModelRunRead",
    "ModelStatus",
    "Neighbourhood",
    "PartRead",
    "Registry",
    "Relationship",
    "RelationshipKindRead",
    "RelationshipRead",
    "RelationshipType",
    "ResourceEnvironment",
]
