"""The knowledge graph, explored (LEKA-369): search, walks, paths, views.

The company model's entities and relationships ARE the graph: an edge
table, an index for each way, walked one step — one query — at a time
(docs/adr/001-postgresql.md). What this service answers:

    search()    the entities whose names and words match what was typed,
                the best first, where each is, and what the ones found say
                of one another (search.py)
    walk()      what is reached from some entities, 1 to MAX_DEPTH steps,
                one way or both, through the relationships asked
    paths()     the shortest ways between two entities, MAX_PATHS at most
    view()      a landscape of the company, its coverage and its sources
                (views.py)
    coverage()  how well the model knows each kind, and from where

Every walk is bounded — by depth, by the entities it may reach, by the
rows a step may read — and says when it stopped short (`truncated`). The
removed are never walked through; a root may be one.

Read by leka.api for people, and by the modules above (leka.context) for
what they need of the graph.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from leka.ingestion import monitoring_kinds
from leka.knowledge.models import Entity, EntityType, Relationship, RelationshipType
from leka.knowledge.repository import GraphRepository
from leka.knowledge.schemas import (
    EntityBrief,
    GraphNodeRead,
    GraphRead,
    GraphRelationshipRead,
    KindCoverageRead,
    KnowledgeCoverageRead,
    LandscapeViewRead,
    PathRead,
    PathsRead,
    RelationshipRead,
    SearchHit,
    SearchResults,
    ViewEdgeRead,
    ViewLayerRead,
    ViewNodeRead,
    ViewSourceRead,
)
from leka.knowledge.search import fold, query
from leka.knowledge.views import (
    MAX_PER_LAYER,
    VIEWS,
    Placed,
    Tie,
    coverage,
    deduced,
    layout,
    state,
)

# A search's entities, at most, and the relationships among them.
MAX_HITS = 50
MAX_HIT_RELATIONSHIPS = 50
# A walk: its steps, its roots, the entities it may reach, the rows a step
# may read each way, the relationships it returns. Four steps is the ADR's
# watch line: past it, a walk of the whole company, not of a thing's
# surroundings.
MAX_DEPTH = 4
MAX_ROOTS = 10
MAX_NODES = 500
MAX_STEP_ROWS = 5_000
MAX_RELATIONSHIPS = 2_000
# A path: the ways returned, the entities a search for one may visit.
MAX_PATHS = 5
MAX_VISITED = 5_000
# What the services' state reads: an incident in the last week.
RECENT_INCIDENT = timedelta(days=7)

Direction = Literal["outgoing", "incoming", "both"]
WAYS: dict[Direction, bool | None] = {"outgoing": True, "incoming": False, "both": None}


class GraphService:
    """Explores the company model's graph."""

    def __init__(self, graph: GraphRepository) -> None:
        self._graph = graph

    async def search(
        self,
        typed: str,
        *,
        types: Sequence[EntityType] = (),
        removed: bool = False,
        limit: int = MAX_HITS,
    ) -> SearchResults:
        """The entities matching what was typed, the best first — none when
        nothing searchable was typed — and the relationships among them."""
        tsquery = query(typed)
        if tsquery is None:
            return SearchResults(query=typed, entities=[], relationships=[])
        found = await self._graph.search(
            tsquery, fold(typed), types=types, removed=removed, limit=min(limit, MAX_HITS)
        )
        named = {entity.id: entity for entity, _ in found}
        holders = await self._graph.holders(list(named))
        among = await self._graph.between(list(named), limit=MAX_HIT_RELATIONSHIPS)
        kinds = await self._kinds(named.values())
        return SearchResults(
            query=typed,
            entities=[
                SearchHit(
                    entity=EntityBrief.model_validate(entity),
                    score=round(score, 4),
                    holder=_brief(holders.get(entity.id)),
                    sources=_sources(entity, kinds),
                )
                for entity, score in found
            ],
            relationships=[_named(edge, named) for edge in among],
        )

    async def walk(
        self,
        roots: Sequence[uuid.UUID],
        *,
        depth: int = 1,
        direction: Direction = "both",
        types: Sequence[RelationshipType] = (),
        entity_types: Sequence[EntityType] = (),
        min_confidence: float | None = None,
        environment: str | None = None,
        limit: int = MAX_NODES,
    ) -> GraphRead | None:
        """What is reached from `roots`, `depth` steps away at most, one way
        or both, through `types` (every kind when none) — only entities of
        `entity_types` when asked — and the relationships among all of it,
        whichever way they point: the direction says how far the walk goes,
        not which truths it shows. None when a root is not the workspace's."""
        wanted = list(dict.fromkeys(roots))[:MAX_ROOTS]
        found = await self._graph.by_ids(wanted)
        if not wanted or len(found) != len(wanted):
            return None
        depth = min(max(depth, 1), MAX_DEPTH)
        limit = min(max(limit, 1), MAX_NODES)
        reached: dict[uuid.UUID, int] = dict.fromkeys(wanted, 0)
        entities: dict[uuid.UUID, Entity] = dict(found)
        frontier = list(wanted)
        truncated = False
        for level in range(1, depth + 1):
            steps = await self._graph.step(
                frontier,
                outgoing=WAYS[direction],
                types=types,
                entity_types=entity_types,
                min_confidence=min_confidence,
                environment=environment,
                limit=MAX_STEP_ROWS,
            )
            truncated = truncated or len(steps) >= MAX_STEP_ROWS
            frontier = []
            for _, far in steps:
                if far.id in reached:
                    continue
                if len(reached) >= limit:
                    truncated = True
                    break
                reached[far.id] = level
                entities[far.id] = far
                frontier.append(far.id)
            if not frontier or len(reached) >= limit:
                break
        edges = await self._graph.between(
            list(reached),
            types=types,
            min_confidence=min_confidence,
            environment=environment,
            limit=MAX_RELATIONSHIPS + 1,
        )
        truncated = truncated or len(edges) > MAX_RELATIONSHIPS
        kinds = await self._kinds(entities.values())
        return GraphRead(
            roots=[EntityBrief.model_validate(found[i]) for i in wanted],
            depth=depth,
            direction=direction,
            nodes=[
                GraphNodeRead(
                    entity=EntityBrief.model_validate(entities[i]),
                    depth=distance,
                    sources=_sources(entities[i], kinds),
                )
                for i, distance in reached.items()
            ],
            relationships=[RelationshipRead.model_validate(e) for e in edges[:MAX_RELATIONSHIPS]],
            truncated=truncated,
        )

    async def paths(
        self,
        start: uuid.UUID,
        end: uuid.UUID,
        *,
        max_depth: int = MAX_DEPTH,
        types: Sequence[RelationshipType] = (),
        min_confidence: float | None = None,
    ) -> PathsRead | None:
        """The shortest ways from `start` to `end` — through relationships
        read either way, `types` only when asked — MAX_PATHS at most, the
        surest first. None when either is not the workspace's.

        Two searches, one from each end, meet in the middle — the smaller
        frontier steps first — each step reading the relationships' ids and
        ends only: four steps from a hub are two from each end, not the
        whole company loaded."""
        ends = await self._graph.by_ids([start, end])
        if start not in ends or end not in ends:
            return None
        if start == end:
            brief = EntityBrief.model_validate(ends[start])
            return PathsRead(
                start=brief,
                end=brief,
                length=0,
                paths=[PathRead(entities=[brief], relationships=[])],
                truncated=False,
            )
        max_depth = min(max(max_depth, 1), MAX_DEPTH)
        ahead, behind = _Search.at(start), _Search.at(end)
        truncated = False
        met: list[uuid.UUID] = []
        while ahead.level + behind.level < max_depth:
            side, other = (
                (ahead, behind) if len(ahead.frontier) <= len(behind.frontier) else (behind, ahead)
            )
            steps = await self._graph.ties(
                side.frontier, types=types, min_confidence=min_confidence, limit=MAX_STEP_ROWS
            )
            truncated = truncated or len(steps) >= MAX_STEP_ROWS
            room = MAX_VISITED - len(ahead.depth) - len(behind.depth)
            truncated = side.step(steps, room) or truncated
            met = [one for one in side.frontier if one in other.depth]
            if met or not side.frontier:
                break
        found = _joined(ahead, behind, met)
        entities = await self._graph.by_ids([one for ids, _ in found for one in ids])
        edges = await self._graph.edges_by_ids([one for _, links in found for one in links])
        return PathsRead(
            start=EntityBrief.model_validate(ends[start]),
            end=EntityBrief.model_validate(ends[end]),
            length=ahead.level + behind.level if met else None,
            paths=[
                PathRead(
                    entities=[EntityBrief.model_validate(entities[i]) for i in ids],
                    relationships=[RelationshipRead.model_validate(edges[i]) for i in links],
                )
                for ids, links in found
            ],
            truncated=truncated,
        )

    async def view(self, name: str, *, now: datetime) -> LandscapeViewRead:
        """A landscape of the company (views.py): its layers' boxes, the
        lines between them, each thing's state, the view's coverage and its
        sources."""
        view = VIEWS[name]
        among = view.types
        layers: list[ViewLayerRead] = []
        drawn: list[tuple[str, Entity]] = []
        # What the view's relationships tie to each set of kinds, by type,
        # once: the dependency view's five rows share theirs.
        tied: dict[tuple[EntityType, ...], dict[str, set[uuid.UUID]]] = {}
        for layer in view.layers:
            if layer.tied and layer.tied not in tied:
                tied[layer.tied] = await self._graph.tied(view.links, layer.tied)
            kinds = layer.types
            found: list[Entity] = []
            total = 0
            for candidate in (layer.types, layer.fallback):
                if not candidate:
                    continue
                kinds = candidate
                within = (
                    {one for kind in candidate for one in tied[layer.tied].get(kind.value, ())}
                    if layer.tied
                    else None
                )
                found, total = await self._graph.layer(
                    candidate, within=within, limit=MAX_PER_LAYER
                )
                if total:
                    break
            layers.append(
                ViewLayerRead(name=layer.name, types=list(kinds), total=total, shown=len(found))
            )
            drawn += [(layer.name, entity) for entity in found]
        shown_by = await self._kinds(entity for _, entity in drawn)
        placed = [
            Placed(
                id=entity.id,
                type=entity.type.value,
                key=entity.key,
                name=entity.name,
                layer=row,
                attributes=dict(entity.attributes),
                kinds=frozenset(_sources(entity, shown_by)),
            )
            for row, entity in drawn
        ]
        ids = [thing.id for thing in placed]
        ties = await self._graph.between(ids, types=view.links, limit=MAX_RELATIONSHIPS)
        owned = await self._graph.around(ids, (RelationshipType.OWNED_BY,))
        owners = await self._graph.by_ids([e.to_entity_id for e in owned])
        teams: dict[uuid.UUID, uuid.UUID] = {}
        for edge in sorted(owned, key=lambda e: -e.confidence):
            owner = owners.get(edge.to_entity_id)
            if owner is not None and owner.type is EntityType.TEAM:
                teams.setdefault(edge.from_entity_id, owner.id)
        services = [thing.id for thing in placed if thing.type == EntityType.SERVICE]
        hit = await self._graph.recently_hit(services, since=now - RECENT_INCIDENT)
        monitoring = monitoring_kinds()
        statuses = {
            thing.id: state(thing, monitoring=monitoring, recently_hit=thing.id in hit)
            for thing in placed
        }
        guessed = {
            thing.id: deduced(thing, monitoring=monitoring, recently_hit=thing.id in hit)
            for thing in placed
        }
        boxes, lines = layout(
            view,
            placed,
            [Tie(e.from_entity_id, e.to_entity_id, e.type.value) for e in ties],
            statuses,
            teams,
            guessed,
        )
        return LandscapeViewRead(
            view=view.name,
            built_at=await self._graph.built_at(),
            layers=layers,
            nodes=[
                ViewNodeRead(
                    id=box.id,
                    type=box.type,
                    layer=box.layer,
                    name=box.name,
                    status=box.status,
                    entity_id=box.entity_id,
                    key=box.key,
                    detail=box.detail,
                    count=box.count,
                    environment=box.environment,
                    team=_brief(owners.get(box.team_id)) if box.team_id else None,
                    deduced=box.deduced,
                )
                for box in boxes
            ],
            edges=[
                ViewEdgeRead(
                    from_id=line.from_id, to_id=line.to_id, type=line.type, status=line.status
                )
                for line in lines
            ],
            coverage=await self._coverage(among),
            sources=await self._sources(among),
        )

    async def coverage(self) -> KnowledgeCoverageRead:
        """How well the model knows each kind it holds, and from which
        sources."""
        kinds = list(EntityType)
        return KnowledgeCoverageRead(
            built_at=await self._graph.built_at(),
            kinds=await self._coverage(kinds),
            sources=await self._sources(kinds),
        )

    async def _kinds(self, entities: Iterable[Entity]) -> dict[uuid.UUID, str]:
        """The kinds of the sources these entities come from."""
        return await self._graph.source_kinds(
            list({source for entity in entities for source in _source_ids(entity)})
        )

    async def _coverage(self, kinds: Sequence[EntityType]) -> list[KindCoverageRead]:
        return [
            KindCoverageRead(
                type=EntityType(row.type),
                total=row.total,
                owned=row.owned,
                documented=row.documented,
                corroborated=row.corroborated,
                connected=row.connected,
            )
            for row in coverage(await self._graph.known(kinds))
        ]

    async def _sources(self, kinds: Sequence[EntityType]) -> list[ViewSourceRead]:
        return [
            ViewSourceRead(source_id=source, kind=kind, entities=count)
            for source, kind, count in await self._graph.sources_of(kinds)
        ]


@dataclass
class _Search:
    """One end's half of a search for a way: how far each entity reached is
    from that end, and each one's parents — the entity before it on a
    shortest way, through which relationship, how sure."""

    depth: dict[uuid.UUID, int]
    parents: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, float]]]
    frontier: list[uuid.UUID]
    level: int = 0

    @classmethod
    def at(cls, origin: uuid.UUID) -> _Search:
        return cls(depth={origin: 0}, parents={origin: []}, frontier=[origin])

    def step(
        self, ties: Iterable[tuple[uuid.UUID, uuid.UUID, uuid.UUID, float]], room: int
    ) -> bool:
        """One step further, through these relationships, `room` more
        entities at most: whether some were left out."""
        self.level += 1
        reached: list[uuid.UUID] = []
        short = False
        for tie, a, b, sure in ties:
            for near, far in ((a, b), (b, a)):
                if self.depth.get(near) != self.level - 1:
                    continue
                seen = self.depth.get(far)
                if seen is None:
                    if len(reached) >= room:
                        short = True
                        continue
                    self.depth[far] = self.level
                    self.parents[far] = []
                    reached.append(far)
                elif seen != self.level:
                    continue
                self.parents[far].append((near, tie, sure))
        self.frontier = reached
        return short

    def ways(self, to: uuid.UUID) -> list[tuple[list[uuid.UUID], list[uuid.UUID], float]]:
        """The shortest ways from this end to `to`: the entities and the
        relationships in order, and how sure the least sure of them is —
        MAX_PATHS at most, the surest first."""
        found: list[tuple[list[uuid.UUID], list[uuid.UUID], float]] = []
        stack: list[tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID], float]] = [
            (to, [to], [], 1.0)
        ]
        while stack and len(found) < MAX_PATHS:
            node, ids, links, sure = stack.pop()
            parents = self.parents.get(node, [])
            if not parents:
                found.append((ids[::-1], links[::-1], sure))
                continue
            # Pushed weakest first: the surest come off the stack first.
            for parent, tie, confidence in sorted(parents, key=lambda p: p[2]):
                if parent not in ids:
                    stack.append((parent, [*ids, parent], [*links, tie], min(sure, confidence)))
        return found


def _joined(
    ahead: _Search, behind: _Search, met: Sequence[uuid.UUID]
) -> list[tuple[list[uuid.UUID], list[uuid.UUID]]]:
    """The whole ways through where the two searches met: from the start to
    each meeting point, then on to the end — MAX_PATHS at most, the surest
    first."""
    whole: list[tuple[float, list[uuid.UUID], list[uuid.UUID]]] = []
    for middle in met:
        for there, first, sure in ahead.ways(middle):
            for back, then, other in behind.ways(middle):
                whole.append((min(sure, other), there + back[::-1][1:], first + then[::-1]))
    whole.sort(key=lambda way: -way[0])
    return [(ids, links) for _, ids, links in whole[:MAX_PATHS]]


def _named(edge: Relationship, named: dict[uuid.UUID, Entity]) -> GraphRelationshipRead:
    return GraphRelationshipRead(
        **RelationshipRead.model_validate(edge).model_dump(),
        from_entity=EntityBrief.model_validate(named[edge.from_entity_id]),
        to_entity=EntityBrief.model_validate(named[edge.to_entity_id]),
        provenance=list(edge.provenance),
        first_seen_at=edge.first_seen_at,
        changed_at=edge.changed_at,
    )


def _brief(entity: Entity | None) -> EntityBrief | None:
    return EntityBrief.model_validate(entity) if entity is not None else None


def _source_ids(entity: Entity) -> set[uuid.UUID]:
    """The sources in an entity's provenance."""
    sources = (entity.provenance or {}).get("sources")
    found: set[uuid.UUID] = set()
    for source in sources if isinstance(sources, list) else []:
        try:
            found.add(uuid.UUID(str(source.get("source_id"))))
        except (AttributeError, ValueError):
            continue
    return found


def _sources(entity: Entity, kinds: dict[uuid.UUID, str]) -> list[str]:
    """The kinds of the sources that show it: github, pagerduty…"""
    return sorted({kinds[s] for s in _source_ids(entity) if s in kinds})
