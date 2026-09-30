"""Business logic over the company model.

What leka.context and leka.intentions ask of the graph: an entity, its
neighbourhood, its history; the landscape of applications and services,
and what depends on what (LEKA-362). The registry (registry.py) is what
they read to know what kinds of things a company is made of.

Depends on leka.ingestion. Must not import leka.context or leka.intentions
(architecture rule 1).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from leka.knowledge.models import Entity, EntityType, Relationship, RelationshipType
from leka.knowledge.repository import EntityRepository
from leka.knowledge.schemas import (
    Criticality,
    Dependencies,
    DependencyNode,
    DependencyRead,
    EntityBrief,
    EntityRead,
    LandscapeDetail,
    LandscapeRead,
    Neighbourhood,
    PartRead,
    RelationshipRead,
)

MAX_DEPTH = 3
MAX_ENTITIES = 200
# The dependency walk: how far, how many.
MAX_DEPENDENCY_DEPTH = 5
MAX_DEPENDENCIES = 500
# What a service's detail lists of its parts and dependencies.
MAX_LISTED = 200
AROUND = (
    RelationshipType.PART_OF,
    RelationshipType.OWNED_BY,
    RelationshipType.MAINTAINED_BY,
    RelationshipType.DEPENDS_ON,
)


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

    # ── the landscape (LEKA-362) ─────────────────────────────────────────────

    async def landscape(self, found: Sequence[Entity]) -> list[LandscapeRead]:
        """A page of services or applications, each with what the
        landscape says of it."""
        rows, _, _ = await self._landscape(found)
        return rows

    async def detail(self, entity: Entity) -> LandscapeDetail:
        """One service or application: what it is made of, what it depends
        on and what depends on it — the surest first, up to MAX_LISTED each."""
        [row], edges, others = await self._landscape([entity])
        parts = sorted(
            (
                e
                for e in edges
                if e.type is RelationshipType.PART_OF and e.to_entity_id == entity.id
            ),
            key=lambda e: -e.confidence,
        )[:MAX_LISTED]
        return LandscapeDetail(
            **row.model_dump(),
            attributes=dict(entity.attributes),
            provenance=dict(entity.provenance),
            parts=[
                PartRead(
                    entity=EntityBrief.model_validate(others[e.from_entity_id]),
                    environments=_environments(e),
                )
                for e in parts
                if e.from_entity_id in others
            ],
            depends_on=_dependencies(edges, others, entity.id, outgoing=True),
            depended_on_by=_dependencies(edges, others, entity.id, outgoing=False),
        )

    async def dependencies(
        self,
        entity_id: uuid.UUID,
        *,
        direction: Literal["downstream", "upstream"],
        depth: int,
        environment: str | None,
    ) -> Dependencies | None:
        """What an entity depends on, `depth` steps away at most — or what
        depends on it — in one environment or all. None when the workspace
        has no such entity."""
        depth = min(max(depth, 1), MAX_DEPENDENCY_DEPTH)
        reached, edges = await self._entities.dependencies(
            entity_id,
            downstream=direction == "downstream",
            depth=depth,
            environment=environment,
            limit=MAX_DEPENDENCIES + 1,
        )
        if entity_id not in reached:
            return None
        truncated = len(reached) > MAX_DEPENDENCIES
        kept = dict(list(reached.items())[:MAX_DEPENDENCIES])
        kept[entity_id] = 0
        found = await self._entities.by_ids(list(kept))
        return Dependencies(
            root=EntityBrief.model_validate(found[entity_id]),
            direction=direction,
            environment=environment,
            depth=depth,
            nodes=[
                DependencyNode(
                    entity=EntityBrief.model_validate(found[other]),
                    depth=distance,
                    criticality=_level(found[other]),
                )
                for other, distance in sorted(kept.items(), key=lambda item: item[1])
                if other != entity_id and other in found
            ],
            relationships=[
                RelationshipRead.model_validate(edge)
                for edge in edges
                if edge.from_entity_id in kept and edge.to_entity_id in kept
            ],
            truncated=truncated,
        )

    async def _landscape(
        self, found: Sequence[Entity]
    ) -> tuple[list[LandscapeRead], list[Relationship], dict[uuid.UUID, Entity]]:
        ids = [entity.id for entity in found]
        edges = list(await self._entities.around(ids, AROUND))
        ends = {e.from_entity_id for e in edges} | {e.to_entity_id for e in edges}
        others = await self._entities.by_ids(list(ends - set(ids)))
        others |= {entity.id: entity for entity in found}
        outgoing: dict[tuple[uuid.UUID, RelationshipType], list[Relationship]] = defaultdict(list)
        incoming: dict[tuple[uuid.UUID, RelationshipType], list[Relationship]] = defaultdict(list)
        for edge in edges:
            outgoing[(edge.from_entity_id, edge.type)].append(edge)
            incoming[(edge.to_entity_id, edge.type)].append(edge)

        def briefs(
            of: uuid.UUID, relation: RelationshipType, kind: EntityType
        ) -> list[EntityBrief]:
            targets = [others.get(e.to_entity_id) for e in outgoing[(of, relation)]]
            return sorted(
                (
                    EntityBrief.model_validate(t)
                    for t in targets
                    if t is not None and t.type is kind
                ),
                key=lambda brief: brief.name.lower(),
            )

        rows = []
        for entity in found:
            services = [
                e
                for e in incoming[(entity.id, RelationshipType.PART_OF)]
                if (other := others.get(e.from_entity_id)) and other.type is EntityType.SERVICE
            ]
            rows.append(
                LandscapeRead(
                    id=entity.id,
                    type=entity.type,
                    key=entity.key,
                    name=entity.name,
                    lifecycle=entity.lifecycle,
                    stage=_text(entity.attributes.get("stage")),
                    criticality=_criticality(entity),
                    environments=_names(entity.attributes.get("environments"))
                    or _names([entity.attributes.get("environment")]),
                    applications=briefs(
                        entity.id, RelationshipType.PART_OF, EntityType.APPLICATION
                    ),
                    owners=briefs(entity.id, RelationshipType.OWNED_BY, EntityType.TEAM),
                    maintainers=briefs(
                        entity.id, RelationshipType.MAINTAINED_BY, EntityType.PERSON
                    ),
                    services=len(services),
                    dependencies=len(outgoing[(entity.id, RelationshipType.DEPENDS_ON)]),
                    dependents=len(incoming[(entity.id, RelationshipType.DEPENDS_ON)]),
                    last_seen_at=entity.last_seen_at,
                )
            )
        return rows, edges, others


def _criticality(entity: Entity) -> Criticality | None:
    """How critical, and who says so: a source (a catalogue, a tag) or
    enrichment (its parts)."""
    level = _text(entity.attributes.get("criticality"))
    if level is None:
        return None
    origins = entity.provenance.get("attributes")
    origin = origins.get("criticality") if isinstance(origins, dict) else None
    said = origin if isinstance(origin, dict) else {}
    confidence = said.get("confidence", entity.attributes.get("criticality_confidence"))
    return Criticality(
        level=level,
        origin=str(said.get("origin") or "source"),
        confidence=float(confidence) if isinstance(confidence, int | float) else None,
        raw=_text(entity.attributes.get("criticality_raw")),
    )


def _level(entity: Entity) -> str | None:
    return _text(entity.attributes.get("criticality"))


def _dependencies(
    edges: list[Relationship],
    others: dict[uuid.UUID, Entity],
    entity_id: uuid.UUID,
    *,
    outgoing: bool,
) -> list[DependencyRead]:
    found = [
        e
        for e in edges
        if e.type is RelationshipType.DEPENDS_ON
        and (e.from_entity_id if outgoing else e.to_entity_id) == entity_id
    ]
    found.sort(key=lambda e: -e.confidence)
    listed = []
    for edge in found[:MAX_LISTED]:
        other = others.get(edge.to_entity_id if outgoing else edge.from_entity_id)
        if other is None:
            continue
        listed.append(
            DependencyRead(
                entity=EntityBrief.model_validate(other),
                confidence=edge.confidence,
                origin=edge.origin,
                environments=_environments(edge),
            )
        )
    return listed


def _environments(edge: Relationship) -> list[str]:
    return _names((edge.attributes or {}).get("environments"))


def _names(value: object) -> list[str]:
    return [str(v) for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
