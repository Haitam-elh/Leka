"""The company model, read (LEKA-361).

    GET /knowledge/model                       where it stands: pending?, the last
                                               build, how many of each type
    GET /knowledge/registry                    the kinds of things a company is made
                                               of, their versions and attributes
    GET /knowledge/entities                    the entities — by type, lifecycle,
                                               name; the removed only when asked
    GET /knowledge/entities/{id}               one: its provenance, its relationships
    GET /knowledge/entities/{id}/versions      its history, the latest first
    GET /knowledge/entities/{id}/neighbourhood what surrounds it, 1 to 3 steps away

Read by every member (`workspace:read`): it is the company's own picture. A
route validates, calls one repository or service, and returns (architecture
rule 6). The workspace is read from the session, never from the path or the
payload (rule 3): another workspace's entity is 404.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.core.errors import ErrorCode
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission
from leka.ingestion import EnrichmentRepository
from leka.knowledge import (
    ENTITY_KINDS,
    MODEL_VERSION,
    RELATIONSHIP_KINDS,
    Entity,
    EntityBrief,
    EntityDetail,
    EntityKindRead,
    EntityRead,
    EntityRepository,
    EntityType,
    EntityVersionRead,
    KnowledgeService,
    Lifecycle,
    LinkRead,
    ModelRepository,
    ModelRunRead,
    ModelStatus,
    Neighbourhood,
    Registry,
    RelationshipKindRead,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]

# An entity's relationships in its detail; its neighbourhood pages the rest.
EDGES = 100

ENTITY_SORTS = SortCatalogue(
    fields=(SortableField("name", Entity.name, "ix_entities_workspace_type_name"),),
    default="name",
)


@router.get("/model", response_model=ModelStatus)
async def model_status(session: SessionDep, principal: Reader) -> ModelStatus:
    """Whether enrichment made something the last build has not read, the
    last build, and what the model holds."""
    model = ModelRepository(session, principal.workspace_id)
    basis = await EnrichmentRepository(session, principal.workspace_id).latest_enrichment()
    last = await model.latest_run()
    counts = await EntityRepository(session, principal.workspace_id).counts()
    return ModelStatus(
        pending=await model.pending(basis, MODEL_VERSION),
        model_version=MODEL_VERSION,
        last_run=ModelRunRead.model_validate(last) if last else None,
        **counts,
    )


@router.get("/registry", response_model=Registry)
async def registry(principal: Reader) -> Registry:
    """The kinds of things a company is made of: each entity type — its
    version, its category, the attributes its schema declares, the
    ingestion types it is built from — and each relationship type."""
    return Registry(
        model_version=MODEL_VERSION,
        entities=[
            EntityKindRead(
                type=kind.type,
                version=kind.version,
                category=kind.category,
                attributes=sorted(kind.attributes.model_fields),
                built_from=list(kind.built_from),
            )
            for kind in ENTITY_KINDS.values()
        ],
        relationships=[
            RelationshipKindRead(
                type=kind.type, version=kind.version, built_from=list(kind.built_from)
            )
            for kind in RELATIONSHIP_KINDS.values()
        ],
    )


@router.get("/entities", response_model=PageEnvelope[EntityRead])
async def entities(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    type: EntityType | None = None,  # noqa: A002 — the API's word
    lifecycle: Annotated[
        Lifecycle | None,
        Query(description="Absent: every lifecycle but removed."),
    ] = None,
    q: Annotated[str | None, Query(max_length=200, description="In the name.")] = None,
) -> PageEnvelope[EntityRead]:
    """The company's entities, by name."""
    statement = EntityRepository(session, principal.workspace_id).entities()
    if type is not None:
        statement = statement.where(Entity.type == type)
    if lifecycle is None:
        statement = statement.where(Entity.lifecycle != Lifecycle.REMOVED)
    else:
        statement = statement.where(Entity.lifecycle == lifecycle)
    if q:
        statement = statement.where(Entity.name.ilike(f"%{q}%"))
    result = await serve_page(
        session, statement, request=page, catalogue=ENTITY_SORTS, id_column=Entity.id
    )
    return PageEnvelope(
        data=[EntityRead.model_validate(entity) for entity in result.items],
        next_cursor=result.next_cursor,
    )


@router.get("/entities/{entity_id}", response_model=EntityDetail)
async def entity(entity_id: uuid.UUID, session: SessionDep, principal: Reader) -> EntityDetail:
    """One entity: where every piece of it came from, and its relationships
    — the surest first, up to 100."""
    repository = EntityRepository(session, principal.workspace_id)
    found = await repository.get(Entity, entity_id)
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    edges, total = await repository.edges_of(found.id, limit=EDGES)
    others = await repository.by_ids(
        [e.to_entity_id if e.from_entity_id == found.id else e.from_entity_id for e in edges]
    )
    links = []
    for edge in edges:
        outgoing = edge.from_entity_id == found.id
        other = others.get(edge.to_entity_id if outgoing else edge.from_entity_id)
        if other is None:
            continue
        links.append(
            LinkRead.model_validate(
                {
                    **{
                        key: getattr(edge, key)
                        for key in (
                            "id",
                            "from_entity_id",
                            "to_entity_id",
                            "type",
                            "confidence",
                            "origin",
                            "rule",
                            "cross_source",
                        )
                    },
                    "direction": "out" if outgoing else "in",
                    "other": EntityBrief.model_validate(other),
                }
            )
        )
    versions = await repository.versions_of(found.id)
    return EntityDetail(
        **EntityRead.model_validate(found).model_dump(),
        provenance=dict(found.provenance),
        relationships=links,
        relationships_total=total,
        versions=len(versions),
    )


@router.get("/entities/{entity_id}/versions", response_model=list[EntityVersionRead])
async def versions(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> list[EntityVersionRead]:
    """An entity's history: what it said at each version, and what changed."""
    repository = EntityRepository(session, principal.workspace_id)
    if await repository.get(Entity, entity_id) is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return [EntityVersionRead.model_validate(v) for v in await repository.versions_of(entity_id)]


@router.get("/entities/{entity_id}/neighbourhood", response_model=Neighbourhood)
async def neighbourhood(
    entity_id: uuid.UUID,
    session: SessionDep,
    principal: Reader,
    depth: Annotated[int, Query(ge=1, le=3)] = 1,
) -> Neighbourhood:
    """What surrounds an entity, 1 to 3 steps away in either direction: the
    unit leka.context reads."""
    service = KnowledgeService(EntityRepository(session, principal.workspace_id))
    found = await service.neighbourhood(entity_id, depth=depth)
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return found
