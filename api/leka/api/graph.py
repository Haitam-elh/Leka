"""The knowledge graph, explored (LEKA-369).

    GET /knowledge/search             the entities whose names and words match
                                      what was typed, the best first — where
                                      each is, what shows it — and the
                                      relationships among them
    GET /knowledge/graph              what is reached from one entity or a few,
                                      1 to 4 steps, one way or both, through
                                      the relationships asked
    GET /knowledge/graph/paths        the shortest ways between two entities
    GET /knowledge/views/{view}       a landscape of the company — company,
                                      domains, applications, services, data,
                                      infrastructure, organisation, dependencies:
                                      its rows, boxes, lines, states, coverage
                                      and sources
    GET /knowledge/coverage           how well the model knows each kind, and
                                      from which sources

Read by every member (`workspace:read`), like the rest of the model
(knowledge.py). Every walk is bounded and says when it stopped short;
docs/company-model.md § 16 says how far and how fast.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.core.errors import ErrorCode
from leka.governance import Permission, Principal, require_permission
from leka.knowledge import (
    EntityType,
    GraphRead,
    GraphRepository,
    GraphService,
    KnowledgeCoverageRead,
    LandscapeViewRead,
    PathsRead,
    RelationshipType,
    SearchResults,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
View = Literal[
    "company",
    "domains",
    "applications",
    "services",
    "data",
    "infrastructure",
    "organisation",
    "dependencies",
]


def _service(session: SessionDep, principal: Reader) -> GraphService:
    return GraphService(GraphRepository(session, principal.workspace_id))


Service = Annotated[GraphService, Depends(_service)]


@router.get("/search", response_model=SearchResults)
async def search(
    service: Service,
    q: Annotated[str, Query(min_length=1, max_length=200, description="What was typed.")],
    types: Annotated[
        list[EntityType] | None, Query(alias="type", description="Only these kinds.")
    ] = None,
    removed: Annotated[bool, Query(description="The removed too.")] = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResults:
    """The entities whose names — then whose other words — match what was
    typed, every word a prefix, the best first; and what they say of one
    another."""
    return await service.search(q, types=types or (), removed=removed, limit=limit)


@router.get("/graph", response_model=GraphRead)
async def graph(
    service: Service,
    roots: Annotated[
        list[uuid.UUID], Query(alias="root", min_length=1, max_length=10, description="Where from.")
    ],
    depth: Annotated[int, Query(ge=1, le=4)] = 1,
    direction: Literal["outgoing", "incoming", "both"] = "both",
    relationships: Annotated[
        list[RelationshipType] | None,
        Query(alias="relationship", description="Only through these; every kind when none."),
    ] = None,
    entity_types: Annotated[
        list[EntityType] | None, Query(alias="entity_type", description="Only reaching these.")
    ] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    environment: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> GraphRead:
    """What is reached from the roots, `depth` steps away at most, and the
    relationships among it all — the roots first, then the nearest."""
    found = await service.walk(
        roots,
        depth=depth,
        direction=direction,
        types=relationships or (),
        entity_types=entity_types or (),
        min_confidence=min_confidence,
        environment=environment,
        limit=limit,
    )
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return found


@router.get("/graph/paths", response_model=PathsRead)
async def paths(
    service: Service,
    start: Annotated[uuid.UUID, Query(alias="from")],
    end: Annotated[uuid.UUID, Query(alias="to")],
    max_depth: Annotated[int, Query(ge=1, le=4)] = 4,
    relationships: Annotated[
        list[RelationshipType] | None,
        Query(alias="relationship", description="Only through these; every kind when none."),
    ] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
) -> PathsRead:
    """How two entities are tied: the shortest ways between them, five at
    most, the relationships read either way — none past `max_depth` steps."""
    found = await service.paths(
        start,
        end,
        max_depth=max_depth,
        types=relationships or (),
        min_confidence=min_confidence,
    )
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    return found


@router.get("/views/{view}", response_model=LandscapeViewRead)
async def view(view: View, service: Service) -> LandscapeViewRead:
    """A landscape of the company: its rows, the boxes of each — the most
    connected first — the lines between them, each thing's state, how well
    its kinds are known and which sources it comes from."""
    return await service.view(view, now=datetime.now(UTC))


@router.get("/coverage", response_model=KnowledgeCoverageRead)
async def coverage(service: Service) -> KnowledgeCoverageRead:
    """How well the model knows each kind: how many, with an owner,
    documented, said by two sources or more, tied to anything — and the
    sources it comes from."""
    return await service.coverage()
