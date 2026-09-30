"""Data enrichment, read (LEKA-359): what enrichment added to what the
workspace's sources resolve to.

    GET /ingestion/enrichment                   where it stands: pending?, the last
                                                run and its failed enrichers, what
                                                it holds per rule and attribute
    GET /ingestion/enrichment/entities/{id}     one entity as the company model reads
                                                it: its attributes, what enrichment
                                                added, its relationships both ways
    GET /ingestion/enrichment/relationships     every relationship — by type, origin,
                                                rule, cross-source
    GET /ingestion/enrichment/environment       the "Mon environnement" screen (mockup
                                                10): the map, its figures, what needs
                                                attention, what moved last
    GET /ingestion/enrichment/environment/{id}  one entity's sheet (mockup 11)

Read by every member (`source:read`), as resolution is. A route validates,
calls one repository, and returns (architecture rule 6). The workspace is
the session's (rule 3): another workspace's entity is 404.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.core.errors import ErrorCode
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission
from leka.ingestion import (
    ENRICHER_VERSION,
    EnrichedAttributeRead,
    EnrichedEntity,
    EnrichedRelationship,
    EnrichedRelationshipRead,
    EnrichmentRepository,
    EnrichmentRunRead,
    EnrichmentStatus,
    EntityRef,
    EntitySheetRead,
    EnvironmentRead,
    ResolvedEntity,
    ResolvedEntityRead,
    entity_sheet,
    environment_screen,
)

router = APIRouter(prefix="/ingestion/enrichment", tags=["ingestion"])

Reader = Annotated[Principal, Depends(require_permission(Permission.SOURCE_READ))]

# An entity's relationships each way, in its detail; the rest are paged.
EDGES = 100

RELATIONSHIP_SORTS = SortCatalogue(
    fields=(
        SortableField(
            "confidence",
            EnrichedRelationship.confidence,
            "ix_enriched_relationships_workspace_confidence",
        ),
    ),
    default="confidence",
)


@router.get("", response_model=EnrichmentStatus)
async def enrichment_status(session: SessionDep, principal: Reader) -> EnrichmentStatus:
    """Whether resolution made something enrichment has not read, the last
    run — and the enrichers that failed in it — and what it holds."""
    repository = EnrichmentRepository(session, principal.workspace_id)
    last = await repository.latest_run()
    by_rule = await repository.by_rule()
    return EnrichmentStatus(
        pending=await repository.pending(await repository.basis(), ENRICHER_VERSION),
        last_run=EnrichmentRunRead.model_validate(last, from_attributes=True) if last else None,
        counts=await repository.counts(),
        relationships=by_rule["relationships"],
        attributes=by_rule["attributes"],
    )


@router.get("/entities/{entity_id}", response_model=EnrichedEntity)
async def enriched_entity(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> EnrichedEntity:
    """One entity: what its sources say, what enrichment added — each with
    its rule, confidence and evidence — and its relationships, the surest
    first, up to 100 each way."""
    repository = EnrichmentRepository(session, principal.workspace_id)
    return await _enriched(repository, await _entity(repository, entity_id))


@router.get("/environment", response_model=EnvironmentRead)
async def environment(session: SessionDep, principal: Reader) -> EnvironmentRead:
    """The workspace's environment, as mockup 10 lays it out: the map of its
    applications, services, data and infrastructure, their states, what
    needs attention, what moved last."""
    repository = EnrichmentRepository(session, principal.workspace_id)
    return await environment_screen(repository, now=datetime.now(UTC))


@router.get("/environment/{entity_id}", response_model=EntitySheetRead)
async def environment_entity(
    entity_id: uuid.UUID, session: SessionDep, principal: Reader
) -> EntitySheetRead:
    """One entity, as mockup 11 lays it out: its state, owner and team,
    incidents, what moved around it, dependencies and documents."""
    repository = EnrichmentRepository(session, principal.workspace_id)
    entity = await _entity(repository, entity_id)
    enriched = await _enriched(repository, entity)
    return await entity_sheet(repository, entity, enriched, now=datetime.now(UTC))


async def _entity(repository: EnrichmentRepository, entity_id: uuid.UUID) -> ResolvedEntity:
    entity = await repository.get(ResolvedEntity, entity_id)
    if entity is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return entity


async def _enriched(repository: EnrichmentRepository, entity: ResolvedEntity) -> EnrichedEntity:
    outgoing, outgoing_total = await repository.edges_of(entity.id, outgoing=True, limit=EDGES)
    incoming, incoming_total = await repository.edges_of(entity.id, outgoing=False, limit=EDGES)
    ends = await repository.entities_by_id(
        [e.to_entity_id for e in outgoing] + [e.from_entity_id for e in incoming] + [entity.id]
    )
    return EnrichedEntity(
        **ResolvedEntityRead.model_validate(entity, from_attributes=True).model_dump(),
        enriched=[
            EnrichedAttributeRead.model_validate(a, from_attributes=True)
            for a in await repository.enrichments_of(entity.id)
        ],
        outgoing=_read(outgoing, ends),
        outgoing_total=outgoing_total,
        incoming=_read(incoming, ends),
        incoming_total=incoming_total,
    )


@router.get("/relationships", response_model=PageEnvelope[EnrichedRelationshipRead])
async def enriched_relationships(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    type: Annotated[str | None, Query(max_length=50)] = None,  # noqa: A002 — the API's word
    origin: Literal["stated", "inferred"] | None = None,
    rule: Annotated[str | None, Query(max_length=100)] = None,
    cross_source: Annotated[
        bool | None, Query(description="Only the relationships joining two tools' things.")
    ] = None,
    entity_id: Annotated[
        uuid.UUID | None, Query(description="Only those from or to this entity.")
    ] = None,
) -> PageEnvelope[EnrichedRelationshipRead]:
    """The workspace's relationships between resolved entities, the surest
    first."""
    repository = EnrichmentRepository(session, principal.workspace_id)
    statement = repository.relationships_page()
    if type is not None:
        statement = statement.where(EnrichedRelationship.type == type)
    if origin is not None:
        statement = statement.where(EnrichedRelationship.origin == origin)
    if rule is not None:
        statement = statement.where(EnrichedRelationship.rule == rule)
    if cross_source is not None:
        statement = statement.where(EnrichedRelationship.cross_source.is_(cross_source))
    if entity_id is not None:
        statement = statement.where(
            (EnrichedRelationship.from_entity_id == entity_id)
            | (EnrichedRelationship.to_entity_id == entity_id)
        )
    result = await serve_page(
        session,
        statement,
        request=page,
        catalogue=RELATIONSHIP_SORTS,
        id_column=EnrichedRelationship.id,
    )
    ends = await repository.entities_by_id(
        [e.from_entity_id for e in result.items] + [e.to_entity_id for e in result.items]
    )
    return PageEnvelope(data=_read(result.items, ends), next_cursor=result.next_cursor)


def _read(
    edges: Sequence[EnrichedRelationship], ends: dict[uuid.UUID, ResolvedEntity]
) -> list[EnrichedRelationshipRead]:
    """Each relationship with its two ends named — one whose end resolution
    no longer has is left out: the next enrichment run removes it."""
    return [
        EnrichedRelationshipRead(
            type=edge.type,
            origin=edge.origin,
            rule=edge.rule,
            confidence=edge.confidence,
            cross_source=edge.cross_source,
            sources=edge.sources,
            evidence=edge.evidence,
            provenance=list(edge.provenance),
            from_entity=EntityRef.model_validate(ends[edge.from_entity_id], from_attributes=True),
            to_entity=EntityRef.model_validate(ends[edge.to_entity_id], from_attributes=True),
        )
        for edge in edges
        if edge.from_entity_id in ends and edge.to_entity_id in ends
    ]
