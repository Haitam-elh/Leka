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
    architecture()
                what the company runs, in columns, the links between them
                named, and the figures around them (architecture.py)
    coverage()  how well the model knows each kind, and from where
    material()  what leka.context assembles from: a walk's entities and
                relationships with their provenance and the sources named
                (LEKA-370) — gathered(), the same for entities found any
                other way (LEKA-371)
    matching()  the entities a sentence's words find, any of them
    events()    what happened between two dates around some entities
    builds_after(), changes()
                the builds since a date, and what they changed — what
                leka.context follows (LEKA-374)

Every walk is bounded — by depth, by the entities it may reach, by the
rows a step may read — and says when it stopped short (`truncated`). The
removed are never walked through; a root may be one.

Read by leka.api for people, and by the modules above (leka.context) for
what they need of the graph.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from leka.ingestion import monitoring_kinds
from leka.knowledge import architecture as arch
from leka.knowledge.models import Entity, EntityType, Lifecycle, Relationship, RelationshipType
from leka.knowledge.registry import MODEL_VERSION
from leka.knowledge.repository import GraphRepository
from leka.knowledge.schemas import (
    ArchitectureBundleRead,
    ArchitectureCardRead,
    ArchitectureCheckRead,
    ArchitectureFiguresRead,
    ArchitectureFlowRead,
    ArchitectureGroupRead,
    ArchitectureLinkRead,
    ArchitectureRankRead,
    ArchitectureRead,
    ArchitectureSourceRead,
    ChangeFootprint,
    ChangeIncident,
    ChangeReach,
    ChangeTouch,
    ContextMaterial,
    Dispute,
    DisputeSide,
    DisputeSource,
    EntityBrief,
    EntityRead,
    EntityStanding,
    GraphNodeRead,
    GraphRead,
    GraphRelationshipRead,
    KindCoverageRead,
    KnowledgeCoverageRead,
    LandscapeViewRead,
    MaterialEntity,
    MaterialRelationship,
    MaterialSource,
    ModelBuild,
    ModelChange,
    ModelChanges,
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
from leka.knowledge.search import NAMES_APART, any_of, fold, query
from leka.knowledge.service import KnowledgeService
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
# What happened around a thing (LEKA-371): its events, of these kinds, to it
# and to what is part of it, two steps down.
EVENT_KINDS = (
    EntityType.INCIDENT,
    EntityType.DEPLOYMENT,
    EntityType.CHANGE,
    EntityType.RELEASE,
    EntityType.PULL_REQUEST,
)
EVENT_NAMES = {
    EntityType.DEPLOYMENT: "deployment",
    EntityType.CHANGE: "change",
    EntityType.RELEASE: "release",
    EntityType.PULL_REQUEST: "merge",
}
EVENT_SCOPE = 2
MAX_EVENTS = 50
# A change's footprint (LEKA-378): the changes it is drawn for; what they
# are tied to by their sources — part of, affecting, deployed to — of these
# kinds, not an environment or a commit; what depends on that, this far;
# the incidents that followed, at most this many; what of its source's
# words it keeps.
FOOTPRINT_KINDS = (
    EntityType.DEPLOYMENT,
    EntityType.CHANGE,
    EntityType.RELEASE,
    EntityType.PULL_REQUEST,
)
FOOTPRINT_WORDS = {
    EntityType.DEPLOYMENT: "deployment",
    EntityType.CHANGE: "change",
    EntityType.RELEASE: "release",
    EntityType.PULL_REQUEST: "pull_request",
}
FOOTPRINT_TIES = (
    RelationshipType.PART_OF,
    RelationshipType.AFFECTS,
    RelationshipType.DEPLOYED_TO,
)
FOOTPRINT_TOUCHED = (
    EntityType.SERVICE,
    EntityType.APPLICATION,
    EntityType.REPOSITORY,
    EntityType.DATABASE,
    EntityType.INFRA_RESOURCE,
)
FOOTPRINT_DEPTH = 2
FOOTPRINT_SCOPE = 2
FOOTPRINT_DEPENDENCIES = 200
# What an entity depends on that its timeline looks around, at most.
FOOTPRINT_AROUND = 50
FOOTPRINT_INCIDENTS = 20
# What holds a thing for the business (LEKA-379): an application it is part
# of, a capability it supports, a process using it.
STANDING_BUSINESS = (
    RelationshipType.PART_OF,
    RelationshipType.SUPPORTED_BY,
    RelationshipType.USES,
    RelationshipType.REALIZES,
)
STANDING_HOLDERS = (
    EntityType.APPLICATION,
    EntityType.BUSINESS_CAPABILITY,
    EntityType.BUSINESS_PROCESS,
)
FOOTPRINT_DETAILS = ("ref", "commit", "version", "url", "changes", "risk", "title", "number")
# What a dispute can be about (LEKA-382): what runs, keeps data, is the
# company's — not each ticket and commit, whose disagreements follow theirs.
DISPUTED = (
    EntityType.SERVICE,
    EntityType.APPLICATION,
    EntityType.DATABASE,
    EntityType.REPOSITORY,
    EntityType.INFRA_RESOURCE,
    EntityType.TEAM,
    EntityType.PERSON,
    EntityType.BUSINESS_CAPABILITY,
    EntityType.BUSINESS_PROCESS,
)
# The relationships a thing has one of, as the context engine reads them
# (leka.context.ranking.SINGLE): kind, the end that has one, the role.
SINGLE: tuple[tuple[RelationshipType, str, str], ...] = (
    (RelationshipType.OWNED_BY, "from", "owner"),
    (RelationshipType.OWNS, "to", "owner"),
    (RelationshipType.REPORTS_TO, "from", "manager"),
    (RelationshipType.LED_BY, "from", "lead"),
    (RelationshipType.CHILD_OF, "from", "parent"),
)
MAX_DISPUTES = 500

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
                found, total, _ = await self._graph.layer(
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

    async def architecture(
        self, *, now: datetime, environment: str | None, detailed: bool = False
    ) -> ArchitectureRead:
        """What the company runs, in columns (architecture.py): its code,
        services, data, cloud and what it relies on outside — each thing's
        state, deduced where nothing watches it — the links between them
        named, and how many of each there are. Detailed: every card, the
        flows they make, what to confirm, the sources read."""
        most = arch.MAX_CARDS_DETAILED if detailed else arch.MAX_CARDS
        drawn: list[Entity] = []
        degrees: dict[uuid.UUID, int] = {}
        for types, limit in (
            ((EntityType.REPOSITORY,), most),
            ((EntityType.SERVICE, EntityType.APPLICATION), 3 * most),
            ((EntityType.DATABASE,), 3 * most),
            ((EntityType.INFRA_RESOURCE,), 5 * most),
        ):
            found, _, degree = await self._graph.layer(
                types, within=None, limit=limit, outside=True
            )
            drawn += found
            degrees |= degree
        shown_by = await self._kinds(drawn)
        placed = [
            Placed(
                id=entity.id,
                type=entity.type.value,
                key=entity.key,
                name=entity.name,
                layer="",
                attributes=dict(entity.attributes),
                kinds=frozenset(_sources(entity, shown_by)),
            )
            for entity in drawn
        ]
        ids = [thing.id for thing in placed]
        services = [thing.id for thing in placed if thing.type == EntityType.SERVICE]
        hit = await self._graph.recently_hit(services, since=now - RECENT_INCIDENT)
        monitoring = monitoring_kinds()
        things = [
            arch.Thing(
                id=thing.id,
                type=thing.type,
                key=thing.key,
                name=thing.name,
                attributes=thing.attributes,
                status=state(thing, monitoring=monitoring, recently_hit=thing.id in hit),
                deduced=deduced(thing, monitoring=monitoring, recently_hit=thing.id in hit),
                why=_why(entity),
                kinds=thing.kinds,
                degree=degrees.get(thing.id, 0),
            )
            for thing, entity in zip(placed, drawn, strict=True)
        ]
        ties = await self._graph.between(ids, types=arch.LINKS, limit=MAX_RELATIONSHIPS)
        edges = [
            arch.Edge(
                from_id=edge.from_entity_id,
                to_id=edge.to_entity_id,
                type=edge.type.value,
                origin=edge.origin,
                rule=edge.rule,
                confidence=edge.confidence,
                evidence=_evidence(edge),
            )
            for edge in ties
        ]
        owned = await self._graph.around(ids, (RelationshipType.OWNED_BY,))
        owners = await self._graph.by_ids([e.to_entity_id for e in owned])
        teams: dict[uuid.UUID, uuid.UUID] = {}
        for edge in sorted(owned, key=lambda e: -e.confidence):
            owner = owners.get(edge.to_entity_id)
            if owner is not None and owner.type is EntityType.TEAM:
                teams.setdefault(edge.from_entity_id, owner.id)
        # Who maintains each, by their work — never a bot.
        maintained = await self._graph.around(ids, (RelationshipType.MAINTAINED_BY,))
        people = await self._graph.by_ids([e.to_entity_id for e in maintained])
        owners |= people
        maintainers: dict[uuid.UUID, list[uuid.UUID]] = {}
        for edge in sorted(maintained, key=lambda e: -e.confidence):
            person = people.get(edge.to_entity_id)
            if person is not None and person.attributes.get("bot") is not True:
                maintainers.setdefault(edge.from_entity_id, []).append(person.id)
        stats = await self._stats(things)
        totals, providers = await self._census()
        built = arch.build(
            things,
            edges,
            stats=stats,
            teams=teams,
            totals=totals,
            providers=providers,
            monitoring=monitoring,
            environment=environment,
            maintainers=maintainers,
            detailed=detailed,
        )
        read = await self._sources_read(arch.TYPES) if detailed else []
        return ArchitectureRead(
            built_at=await self._graph.built_at(),
            environment=environment,
            environments=built.environments,
            groups=[
                ArchitectureGroupRead(
                    id=g.id,
                    column=g.column,
                    name=g.name,
                    regions=g.regions,
                    total=g.total,
                    shown=g.shown,
                )
                for g in built.groups
            ],
            cards=[
                ArchitectureCardRead(
                    id=card.id,
                    column=card.column,
                    group=card.group,
                    kind=card.kind,
                    type=card.type,
                    name=card.name,
                    entity_id=card.entity_id,
                    key=card.key,
                    status=card.status,
                    deduced=card.deduced,
                    why=card.why,
                    technology=card.technology,
                    description=card.description,
                    environment=card.environment,
                    region=card.region,
                    url=card.url,
                    team=_brief(owners.get(card.team_id)) if card.team_id else None,
                    repository_id=card.repository_id,
                    host_id=card.host_id,
                    deployment=card.deployment,
                    stats=card.stats,
                    evidence=card.evidence,
                    sources=card.sources,
                    facts=card.facts,
                    parts=card.parts,
                    files=card.files,
                    maintainers=[
                        brief
                        for brief in (_brief(owners.get(m)) for m in card.maintainer_ids[:5])
                        if brief is not None
                    ],
                )
                for card in built.cards
            ],
            links=[_link_read(link) for link in built.links],
            bundles=[
                ArchitectureBundleRead(
                    from_id=b.from_id,
                    column=b.column,
                    role=b.role,
                    roles=b.roles,
                    targets=b.targets,
                )
                for b in built.bundles
            ],
            figures=ArchitectureFiguresRead(
                services=totals.get("services", 0),
                applications=totals.get("applications", 0),
                repositories=totals.get("repositories", 0),
                databases=totals.get("databases", 0),
                stores=totals.get("stores", 0),
                cloud_resources=totals.get("cloud", 0),
                providers=providers,
                external=totals.get("external", 0),
                teams=totals.get("teams", 0),
                tables=totals.get("tables", 0),
            ),
            health=built.health,
            services_by_status=built.services,
            top_dependencies=[
                ArchitectureRankRead(card_id=card.id, name=card.name, kind=card.kind, count=n)
                for card, n in built.ranked
            ],
            detailed=detailed,
            flows=[
                ArchitectureFlowRead(
                    entries=flow.entries,
                    steps=[_link_read(link) for link in flow.steps],
                )
                for flow in built.flows
            ],
            checks=[
                ArchitectureCheckRead(
                    kind=check.kind,
                    card_id=check.card_id,
                    other_id=check.other_id,
                    role=check.role,
                    rule=check.rule,
                    confidence=check.confidence,
                )
                for check in built.checks
            ],
            sources=read,
        )

    async def _sources_read(self, kinds: Sequence[EntityType]) -> list[ArchitectureSourceRead]:
        """The sources the architecture was read from: each, when it last
        read, how many of the architecture's things it shows."""
        shown = {source: count for source, _, count in await self._graph.sources_of(kinds)}
        return [
            ArchitectureSourceRead(
                source_id=source,
                kind=kind,
                name=name,
                status=status,
                last_synced_at=synced,
                entities=shown.get(source, 0),
            )
            for source, kind, name, status, synced in await self._graph.sources_read()
        ]

    async def _stats(self, things: Sequence[arch.Thing]) -> dict[uuid.UUID, dict[str, int]]:
        """What the sources count of each card: a repository's commits and
        pull requests, a database's tables and their bytes, a store's
        buckets."""
        repositories = [t.id for t in things if t.type == EntityType.REPOSITORY]
        databases = [t.id for t in things if t.type == EntityType.DATABASE]
        found: dict[uuid.UUID, dict[str, int]] = {}
        work = await self._graph.contents(
            repositories, (EntityType.COMMIT, EntityType.PULL_REQUEST)
        )
        for repository, counts in work.items():
            found[repository] = {
                "commits": counts.get(EntityType.COMMIT.value, 0),
                "pull_requests": counts.get(EntityType.PULL_REQUEST.value, 0),
            }
        for database, (tables, size) in (await self._graph.tables(databases)).items():
            found[database] = {"tables": tables} | ({"size_bytes": size} if size else {})
        return found

    async def _census(self) -> tuple[dict[str, int], dict[str, int]]:
        """How many of each column's kinds there are, and the cloud's by
        provider."""
        totals: dict[str, int] = {}
        providers: dict[str, int] = {}
        for kind, head, attributes, count in await self._graph.census(
            (*arch.TYPES, EntityType.TEAM, EntityType.DATA_OBJECT)
        ):
            if kind == EntityType.TEAM:
                totals["teams"] = totals.get("teams", 0) + count
                continue
            if kind == EntityType.DATA_OBJECT:
                totals["tables"] = totals.get("tables", 0) + count
                continue
            where = arch.column(kind, head, attributes)
            name = {
                ("code", EntityType.REPOSITORY.value): "repositories",
                ("services", EntityType.SERVICE.value): "services",
                ("services", EntityType.APPLICATION.value): "applications",
                ("external", EntityType.SERVICE.value): "external",
                ("data", EntityType.DATABASE.value): "databases",
                ("data", EntityType.INFRA_RESOURCE.value): "stores",
            }.get((where or "", kind), where or "")
            totals[name] = totals.get(name, 0) + count
            if where == "cloud":
                provider = arch.group("cloud", head, attributes)
                providers[provider] = providers.get(provider, 0) + count
        return totals, providers

    async def material(
        self,
        roots: Sequence[uuid.UUID],
        *,
        depth: int = 1,
        types: Sequence[RelationshipType] = (),
        environment: str | None = None,
        limit: int = MAX_NODES,
    ) -> ContextMaterial | None:
        """What leka.context assembles from (LEKA-370): what a walk from
        `roots` reaches, each entity with its provenance and its distance,
        the relationships among them with theirs, the sources named — None
        when none of the roots is the workspace's."""
        walked = await self.walk(
            roots, depth=depth, types=types, environment=environment, limit=limit
        )
        if walked is None:
            return None
        return await self.gathered(
            {node.entity.id: node.depth for node in walked.nodes},
            roots=[root.id for root in walked.roots],
            types=types,
            environment=environment,
            truncated=walked.truncated,
        )

    async def gathered(
        self,
        found: Mapping[uuid.UUID, int | None],
        *,
        roots: Sequence[uuid.UUID],
        types: Sequence[RelationshipType] = (),
        environment: str | None = None,
        truncated: bool = False,
    ) -> ContextMaterial:
        """Some entities, however they were found — a walk, a search, their
        time (LEKA-371) — as leka.context assembles them: each with its
        provenance and its distance when a walk knows it, the relationships
        among them with theirs, the sources named, and which build of the
        model they were read from. The order of `found` is kept; an id that
        is not the workspace's is left out."""
        entities = await self._graph.by_ids(list(found))
        edges = await self._graph.between(
            list(entities), types=types, environment=environment, limit=MAX_RELATIONSHIPS + 1
        )
        ids: set[uuid.UUID] = set()
        for entity in entities.values():
            ids |= _source_ids(entity)
        for edge in edges:
            for record in edge.provenance or []:
                said = _uuid(record.get("source_id")) if isinstance(record, dict) else None
                if said:
                    ids.add(said)
        named = await self._graph.sources_state(list(ids))
        return ContextMaterial(
            roots=[root for root in roots if root in entities],
            entities=[
                MaterialEntity(
                    entity=EntityRead.model_validate(entities[entity_id]),
                    depth=far,
                    provenance=dict(entities[entity_id].provenance or {}),
                )
                for entity_id, far in found.items()
                if entity_id in entities
            ],
            relationships=[
                MaterialRelationship(
                    relationship=RelationshipRead.model_validate(edge),
                    provenance=list(edge.provenance or []),
                    first_seen_at=edge.first_seen_at,
                    changed_at=edge.changed_at,
                )
                for edge in edges[:MAX_RELATIONSHIPS]
            ],
            sources=[
                MaterialSource(source_id=source, kind=kind, name=name, status=status, health=health)
                for source, (kind, name, status, health) in sorted(
                    named.items(), key=lambda i: i[1][1]
                )
            ],
            truncated=truncated or len(edges) > MAX_RELATIONSHIPS,
            built_at=await self._graph.built_at(),
            model_version=MODEL_VERSION,
        )

    async def known(self, ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
        """Which of these are the workspace's entities."""
        return set(await self._graph.by_ids(list(ids)))

    async def briefs(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, EntityBrief]:
        """These entities, named — those that are the workspace's (LEKA-373)."""
        found = await self._graph.by_ids(list(ids))
        return {
            entity_id: EntityBrief.model_validate(entity) for entity_id, entity in found.items()
        }

    async def owners(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[EntityBrief]]:
        """Who owns each of these (LEKA-377): the teams and the people a
        source names as owners — `owned_by` from it, or `owns` to it — the
        removed left out. A thing no source names an owner for is absent."""
        edges = await self._graph.around(
            list(ids), (RelationshipType.OWNED_BY, RelationshipType.OWNS)
        )
        wanted = set(ids)
        pairs = [
            (edge.from_entity_id, edge.to_entity_id)
            if edge.type is RelationshipType.OWNED_BY
            else (edge.to_entity_id, edge.from_entity_id)
            for edge in edges
        ]
        named = await self._graph.by_ids([owner for _, owner in pairs])
        found: dict[uuid.UUID, list[EntityBrief]] = {}
        for thing, owner in pairs:
            entity = named.get(owner)
            if thing not in wanted or entity is None or entity.lifecycle is Lifecycle.REMOVED:
                continue
            briefs = found.setdefault(thing, [])
            if all(brief.id != entity.id for brief in briefs):
                briefs.append(EntityBrief.model_validate(entity))
        return found

    async def disputes(self, *, limit: int = MAX_DISPUTES) -> list[Dispute]:
        """What the model's sources disagree on (LEKA-382): each attribute of
        a thing its sources say differently — resolution chose one, kept
        all — and each relationship a thing has one of, said to several:
        two owners, two managers. With every side, who says it, when; and
        the decision behind what the model shows, when one was taken."""
        sources = {
            source: DisputeSource(
                source_id=source,
                kind=kind,
                name=name,
                status=status,
                synced_at=synced,
                observed_at=None,
            )
            for source, kind, name, status, synced in await self._graph.sources_read()
        }
        found = [
            dispute
            for entity in await self._graph.disputed(DISPUTED, limit=limit)
            for dispute in _attribute_disputes(entity, sources)
        ]
        found += await self._competing(sources)
        return found[:limit]

    async def _competing(self, sources: dict[uuid.UUID, DisputeSource]) -> list[Dispute]:
        edges = await self._graph.single_ties([kind for kind, _, _ in SINGLE], DISPUTED)
        held: dict[tuple[uuid.UUID, str], dict[uuid.UUID, list[Relationship]]] = {}
        for edge in edges:
            for kind, end, role in SINGLE:
                if edge.type is not kind:
                    continue
                subject, other = (
                    (edge.from_entity_id, edge.to_entity_id)
                    if end == "from"
                    else (edge.to_entity_id, edge.from_entity_id)
                )
                held.setdefault((subject, role), {}).setdefault(other, []).append(edge)
        competing = {key: others for key, others in held.items() if len(others) > 1}
        named = await self._graph.by_ids(
            list(
                {
                    thing
                    for (subject, _), others in competing.items()
                    for thing in (subject, *others)
                }
            )
        )
        found: list[Dispute] = []
        for (subject, role), others in sorted(competing.items(), key=lambda pair: str(pair[0])):
            entity = named.get(subject)
            if entity is None or entity.type not in DISPUTED:
                continue
            sides = [
                DisputeSide(
                    value=named[other].name,
                    ref_id=other,
                    origin=_strongest(ties).origin,
                    confidence=_strongest(ties).confidence,
                    sources=_tie_sources(ties, sources),
                    edges=[
                        {
                            "from": str(tie.from_entity_id),
                            "to": str(tie.to_entity_id),
                            "type": tie.type.value,
                        }
                        for tie in ties
                    ],
                )
                for other, ties in sorted(
                    others.items(), key=lambda pair: named[pair[0]].name.casefold()
                )
                if other in named
            ]
            if len(sides) < 2:
                continue
            settled = next(
                (
                    dict(said)
                    for ties in others.values()
                    for tie in ties
                    if tie.origin == "accepted"
                    for said in tie.provenance
                    if isinstance(said, dict) and said.get("conflict_id")
                ),
                None,
            )
            found.append(
                Dispute(
                    kind="relationship",
                    entity=EntityBrief.model_validate(entity),
                    about=role,
                    relationship=next(iter(next(iter(others.values())))).type.value,
                    chosen=None,
                    sides=sides,
                    settled=settled,
                )
            )
        return found

    async def memberships(self, people: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[EntityBrief]]:
        """The teams each of these people is a member of (LEKA-380) — the
        removed left out. Someone in no team is absent."""
        edges = await self._graph.around(list(people), (RelationshipType.MEMBER_OF,))
        wanted = set(people)
        named = await self._graph.by_ids([edge.to_entity_id for edge in edges])
        found: dict[uuid.UUID, list[EntityBrief]] = {}
        for edge in edges:
            team = named.get(edge.to_entity_id)
            if (
                edge.from_entity_id not in wanted
                or team is None
                or team.type is not EntityType.TEAM
                or team.lifecycle is Lifecycle.REMOVED
            ):
                continue
            teams = found.setdefault(edge.from_entity_id, [])
            if all(brief.id != team.id for brief in teams):
                teams.append(EntityBrief.model_validate(team))
        return found

    async def footprints(
        self,
        *,
        since: datetime,
        until: datetime,
        limit: int,
        after: timedelta,
        around: uuid.UUID | None = None,
    ) -> tuple[list[ChangeFootprint], bool]:
        """The changes between two dates — deployments, change requests,
        releases, pull requests — the latest first, each with what the
        model says it reaches (LEKA-378): what it was made to, what depends
        on that, the applications and business holding them, the incidents
        that followed within `after` or say it caused them. `around` an
        entity: the changes made to it, to what it is made of, or to what
        it depends on. And whether there were more than `limit`."""
        scope = None
        if around is not None:
            # It, what it depends on, and what each of those is made of —
            # a change in a repository of a service it calls is around it.
            below, _ = await self._graph.dependencies(
                around,
                downstream=True,
                depth=FOOTPRINT_DEPTH,
                environment=None,
                limit=FOOTPRINT_AROUND,
            )
            scope = set()
            for thing in {around, *below}:
                scope |= await self._graph.scope(thing, depth=FOOTPRINT_SCOPE)
        found, truncated = await self._graph.happened(
            scope=scope, kinds=FOOTPRINT_KINDS, since=since, until=until, limit=limit
        )
        changes = list({thing.id: thing for thing, _ in found}.values())[:limit]
        return [await self._footprint(change, after=after) for change in changes], truncated

    async def footprint(self, change_id: uuid.UUID, *, after: timedelta) -> ChangeFootprint | None:
        """One change, and what it reaches; None when the workspace has no
        such change."""
        found = (await self._graph.by_ids([change_id])).get(change_id)
        if found is None or found.type not in FOOTPRINT_KINDS or found.occurred_at is None:
            return None
        return await self._footprint(found, after=after)

    async def _footprint(self, change: Entity, *, after: timedelta) -> ChangeFootprint:
        at = change.occurred_at or datetime.now(UTC)
        edges = await self._graph.around([change.id], (*FOOTPRINT_TIES, RelationshipType.CAUSED_BY))
        ends = await self._graph.by_ids(
            [e.to_entity_id for e in edges] + [e.from_entity_id for e in edges]
        )
        touched: dict[uuid.UUID, tuple[Entity, str]] = {}
        for edge in sorted(edges, key=lambda e: -e.confidence):
            other = ends.get(edge.to_entity_id)
            if (
                edge.from_entity_id == change.id
                and edge.type in FOOTPRINT_TIES
                and other is not None
                and other.type in FOOTPRINT_TOUCHED
                and other.lifecycle is not Lifecycle.REMOVED
            ):
                touched.setdefault(other.id, (other, edge.type.value))
        # Made in a repository: made to the services it is part of.
        repositories = [e for e, _ in touched.values() if e.type is EntityType.REPOSITORY]
        if repositories:
            lifted = await self._graph.around(
                [r.id for r in repositories], (RelationshipType.PART_OF,)
            )
            holders = await self._graph.by_ids([e.to_entity_id for e in lifted])
            for edge in lifted:
                holder = holders.get(edge.to_entity_id)
                if (
                    holder is not None
                    and edge.from_entity_id in {r.id for r in repositories}
                    and holder.type in (EntityType.SERVICE, EntityType.APPLICATION)
                    and holder.lifecycle is not Lifecycle.REMOVED
                ):
                    touched.setdefault(holder.id, (holder, "via_repository"))
        reached: dict[uuid.UUID, tuple[int, uuid.UUID]] = {}
        for thing in touched:
            depths, _ = await self._graph.dependencies(
                thing,
                downstream=False,
                depth=FOOTPRINT_DEPTH,
                environment=None,
                limit=FOOTPRINT_DEPENDENCIES,
            )
            for dependent, depth in depths.items():
                if dependent in touched or dependent == change.id or depth < 1:
                    continue
                held = reached.get(dependent)
                if held is None or depth < held[0]:
                    reached[dependent] = (depth, thing)
        named = await self._graph.by_ids(list(reached))
        impact = await KnowledgeService(self._graph).impact(list(touched))
        # What followed: on the footprint, within `after`; or saying so.
        footprint = set(touched) | set(reached)
        incidents: dict[uuid.UUID, ChangeIncident] = {}
        stated = [
            e.from_entity_id
            for e in edges
            if e.type is RelationshipType.CAUSED_BY and e.to_entity_id == change.id
        ]
        for incident_id in stated:
            incident = ends.get(incident_id)
            if incident is not None and incident.type is EntityType.INCIDENT:
                incidents[incident.id] = _incident(incident, on=None, stated=True)
        if footprint:
            followed, _ = await self._graph.happened(
                scope=footprint,
                kinds=(EntityType.INCIDENT,),
                since=at,
                until=at + after,
                limit=FOOTPRINT_INCIDENTS,
            )
            on_ids = {via for _, via in followed if via is not None}
            ons = await self._graph.by_ids(list(on_ids))
            for incident, via in followed:
                if incident.occurred_at is None or incident.occurred_at < at:
                    continue
                on = ons.get(via) if via is not None else None
                known = incidents.get(incident.id)
                incidents[incident.id] = _incident(
                    incident, on=on, stated=known is not None and known.stated
                )
        kinds = await self._graph.source_kinds(list(_source_ids(change)))
        a = change.attributes
        return ChangeFootprint(
            change=EntityBrief.model_validate(change),
            kind=FOOTPRINT_WORDS[change.type],
            at=at,
            state=_said(a.get("state")),
            environment=_said(a.get("environment")),
            details={
                name: str(a[name])
                for name in FOOTPRINT_DETAILS
                if isinstance(a.get(name), str | int | float) and str(a[name])
            },
            sources=sorted(set(kinds.values())),
            source_ids=sorted(str(source) for source in _source_ids(change)),
            touched=[
                ChangeTouch(
                    entity=EntityBrief.model_validate(entity),
                    how=how,
                    criticality=_said(entity.attributes.get("criticality")),
                )
                for entity, how in touched.values()
            ],
            reached=sorted(
                (
                    ChangeReach(
                        entity=EntityBrief.model_validate(named[other]),
                        distance=depth,
                        through=EntityBrief.model_validate(touched[through][0]),
                        criticality=_said(named[other].attributes.get("criticality")),
                    )
                    for other, (depth, through) in reached.items()
                    if other in named and named[other].lifecycle is not Lifecycle.REMOVED
                ),
                key=lambda r: (r.distance, r.entity.name.lower()),
            ),
            applications=impact.applications,
            capabilities=impact.capabilities,
            processes=impact.processes,
            incidents=sorted(
                incidents.values(),
                key=lambda i: (not i.stated, i.opened_at or at),
            ),
        )

    async def standing(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, EntityStanding]:
        """What the model holds around each of these (LEKA-379): how
        critical, how documented and how freshly, whether the business
        holds it."""
        things = await self._graph.by_ids(list(ids))
        documented = await self._graph.documented(list(things))
        issues = await self._graph.issue_counts(list(things))
        ties = await self._graph.around(list(things), STANDING_BUSINESS)
        ends = await self._graph.by_ids(
            [e.to_entity_id for e in ties] + [e.from_entity_id for e in ties]
        )
        held: set[uuid.UUID] = set()
        for edge in ties:
            for thing, other in (
                (edge.from_entity_id, edge.to_entity_id),
                (edge.to_entity_id, edge.from_entity_id),
            ):
                found = ends.get(other)
                if thing in things and found is not None and found.type in STANDING_HOLDERS:
                    held.add(thing)
        standing: dict[uuid.UUID, EntityStanding] = {}
        for thing, entity in things.items():
            said = documented[thing]
            standing[thing] = EntityStanding(
                criticality=_said(entity.attributes.get("criticality")),
                stated=_stated(entity.provenance),
                lifecycle=entity.lifecycle,
                documents=said.count,
                fresh_documents=said.fresh,
                last_documented_at=said.last_changed_at,
                business=thing in held,
                confidence=entity.confidence,
                quality=entity.quality,
                last_seen_at=entity.last_seen_at,
                source_ids=tuple(sorted(_source_ids(entity))),
                origins=_origins(entity.provenance),
                disputed=_disputed(entity.provenance),
                issues=issues.get(thing, (0, 0)),
            )
        return standing

    async def documents(self) -> int:
        """How many documents the workspace has, not removed (LEKA-379)."""
        by_freshness, _, _ = await self._graph.documentation_counts()
        return sum(by_freshness.values())

    async def environments(self) -> list[str]:
        """The environments the model knows, folded (LEKA-373)."""
        return await self._graph.environments()

    async def built_at(self) -> datetime | None:
        """When the model was last built (LEKA-373)."""
        return await self._graph.built_at()

    async def builds_after(self, after: datetime | None, *, limit: int) -> list[ModelBuild]:
        """The builds that succeeded since `after`, the oldest first
        (LEKA-374)."""
        return [
            ModelBuild(run_id=run, started_at=started, finished_at=finished)
            for run, started, finished in await self._graph.builds_after(after, limit=limit)
        ]

    async def changes(self, runs: Sequence[uuid.UUID], *, limit: int) -> ModelChanges:
        """What these builds changed (LEKA-374), the oldest first: each entity
        added, changed — and what of it — or removed; each relationship
        that appeared, changed or went, its ends named. At most `limit` of
        each; `truncated` when there was more."""
        versions = await self._graph.recorded(runs, limit=limit + 1)
        edges = await self._graph.changes_in(runs, limit=limit + 1)
        ends = await self._graph.by_ids(
            list({i for edge in edges[:limit] for i in (edge.from_entity_id, edge.to_entity_id)})
        )

        def named(entity_id: uuid.UUID) -> str:
            found = ends.get(entity_id)
            return found.name if found is not None else str(entity_id)

        changes = [
            ModelChange(
                kind="entity",
                change=(
                    "added"
                    if "created" in changed
                    else "removed"
                    if "lifecycle" in changed and lifecycle == "removed"
                    else "changed"
                ),
                entity_id=entity,
                type=kind,
                name=name,
                fields=[] if "created" in changed else changed,
                at=at,
                run_id=run,
            )
            for entity, kind, name, changed, lifecycle, at, run in versions[:limit]
        ] + [
            ModelChange(
                kind="relationship",
                change=edge.change,
                from_id=edge.from_entity_id,
                to_id=edge.to_entity_id,
                type=edge.type,
                name=f"{named(edge.from_entity_id)} → {named(edge.to_entity_id)}",
                at=edge.recorded_at,
                run_id=edge.run_id,
            )
            for edge in edges[:limit]
        ]
        return ModelChanges(
            changes=sorted(changes, key=lambda c: c.at),
            truncated=len(versions) > limit or len(edges) > limit,
        )

    async def matching(
        self, words: Sequence[str], *, limit: int = MAX_HITS
    ) -> list[tuple[uuid.UUID, float, list[str]]]:
        """The entities whose words hold any of `words` — a sentence's, not
        a name typed (LEKA-371) — the best first: the very name, then the
        most words, a name's weighing most; each with the words it holds.
        The removed left out."""
        tsquery = any_of(words)
        if tsquery is None:
            return []
        folded = [w for word in words for w in fold(word).split()]
        found = await self._graph.search(
            tsquery, " ".join(folded), types=(), removed=False, limit=min(limit, MAX_HITS)
        )
        matches: list[tuple[uuid.UUID, float, list[str]]] = []
        for entity, score in found:
            said = f"{entity.search_name} {entity.search_text}".replace(NAMES_APART, " ").split()
            held = [w for w in dict.fromkeys(folded) if any(t.startswith(w) for t in said)]
            matches.append((entity.id, score, held))
        return matches

    async def events(
        self,
        around: Sequence[uuid.UUID],
        *,
        since: datetime,
        until: datetime,
        limit: int = MAX_EVENTS,
    ) -> list[tuple[uuid.UUID, datetime, str, uuid.UUID | None]]:
        """What happened between two dates around some entities (LEKA-371) —
        to each of them or what is part of them, two steps down: an incident
        opened or resolved, a deployment, a change, a release, a merge —
        the latest first, each with when, what, and what it happened to."""
        scope: set[uuid.UUID] = set()
        for entity_id in dict.fromkeys(around):
            scope |= await self._graph.scope(entity_id, depth=EVENT_SCOPE)
        if not scope:
            return []
        found, _ = await self._graph.happened(
            scope=scope, kinds=EVENT_KINDS, since=since, until=until, limit=limit
        )
        happened: list[tuple[uuid.UUID, datetime, str, uuid.UUID | None]] = []
        for entity, via in found:
            resolved = _moment(entity.attributes.get("resolved_at"))
            moments = [(entity.occurred_at, EVENT_NAMES.get(entity.type, entity.type.value))]
            if entity.type is EntityType.INCIDENT:
                moments = [(entity.occurred_at, "incident_opened"), (resolved, "incident_resolved")]
            for at, kind in moments:
                if at is not None and since <= at < until:
                    happened.append((entity.id, at, kind, via))
        happened.sort(key=lambda event: (event[1], str(event[0])), reverse=True)
        return happened[:limit]

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


def _link_read(link: arch.Link) -> ArchitectureLinkRead:
    return ArchitectureLinkRead(
        from_id=link.from_id,
        to_id=link.to_id,
        role=link.role,
        origin=link.origin,
        rule=link.rule,
        confidence=link.confidence,
        evidence=link.evidence,
        status=link.status,
    )


def _why(entity: Entity) -> str | None:
    """What a deduced state was read from: its rule's evidence, as the
    model keeps it."""
    origins = (entity.provenance or {}).get("attributes")
    origin = origins.get("deduced_health") if isinstance(origins, dict) else None
    said = origin.get("evidence") if isinstance(origin, dict) else None
    return said if isinstance(said, str) and said else None


def _evidence(edge: Relationship) -> str | None:
    """The first evidence the records stating a relationship give."""
    for record in edge.provenance or []:
        said = record.get("evidence") if isinstance(record, dict) else None
        if isinstance(said, str) and said:
            return said
    return None


def _brief(entity: Entity | None) -> EntityBrief | None:
    return EntityBrief.model_validate(entity) if entity is not None else None


def _moment(value: object) -> datetime | None:
    """A date an attribute holds — none for what does not read as one."""
    if not isinstance(value, str) or not value:
        return None
    try:
        found = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _said(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _attribute_disputes(entity: Entity, sources: dict[uuid.UUID, DisputeSource]) -> list[Dispute]:
    """An entity's disagreements, as resolution kept them: each attribute
    with two values or more, each value with the sources saying it."""
    provenance = entity.provenance if isinstance(entity.provenance, dict) else {}
    conflicts = provenance.get("conflicts")
    said_of = provenance.get("attributes")
    attributes = said_of if isinstance(said_of, dict) else {}
    found: list[Dispute] = []
    for conflict in conflicts if isinstance(conflicts, list) else []:
        if not isinstance(conflict, dict) or not conflict.get("attribute"):
            continue
        about = str(conflict["attribute"])
        values = conflict.get("values")
        sides: dict[str, DisputeSide] = {}
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict):
                continue
            key = json.dumps(value.get("value"), sort_keys=True, default=str)
            source = _source_of(value, sources)
            held = sides.get(key)
            sides[key] = DisputeSide(
                value=value.get("value"),
                sources=[*(held.sources if held else []), source],
            )
        if len(sides) < 2:
            continue
        current = attributes.get(about)
        settled = (
            dict(current)
            if isinstance(current, dict)
            and current.get("origin") == "accepted"
            and current.get("conflict_id")
            else None
        )
        found.append(
            Dispute(
                kind="attribute",
                entity=EntityBrief.model_validate(entity),
                about=about,
                relationship=None,
                chosen=entity.attributes.get(about, conflict.get("chosen")),
                sides=list(sides.values()),
                settled=settled,
            )
        )
    return found


def _source_of(value: dict[str, object], sources: dict[uuid.UUID, DisputeSource]) -> DisputeSource:
    source = _uuid(value.get("source_id"))
    observed = value.get("observed_at")
    at = observed if isinstance(observed, datetime) else _moment(observed)
    known = sources.get(source) if source else None
    if known is None:
        return DisputeSource(
            source_id=source, kind=None, name=None, status=None, synced_at=None, observed_at=at
        )
    return known.model_copy(update={"observed_at": at})


def _tie_sources(
    ties: list[Relationship], sources: dict[uuid.UUID, DisputeSource]
) -> list[DisputeSource]:
    found: dict[uuid.UUID | None, DisputeSource] = {}
    for tie in ties:
        for said in tie.provenance:
            source = _source_of({**said, "observed_at": tie.changed_at}, sources)
            found.setdefault(source.source_id, source)
    return list(found.values())


def _strongest(ties: list[Relationship]) -> Relationship:
    return max(ties, key=lambda tie: (tie.origin == "stated", tie.confidence))


def _stated(provenance: object) -> tuple[str, ...]:
    """The attributes a source states of an entity, as its provenance says
    — not enrichment's, not a validated fact's (LEKA-380)."""
    attributes = provenance.get("attributes") if isinstance(provenance, dict) else None
    if not isinstance(attributes, dict):
        return ()
    return tuple(
        sorted(
            name
            for name, said in attributes.items()
            if isinstance(said, dict) and said.get("origin", "source") == "source"
        )
    )


def _said_of(provenance: object) -> dict[str, dict[str, object]]:
    attributes = provenance.get("attributes") if isinstance(provenance, dict) else None
    if not isinstance(attributes, dict):
        return {}
    return {name: said for name, said in attributes.items() if isinstance(said, dict)}


def _origins(provenance: object) -> dict[str, int]:
    """Its attributes by origin — source, enrichment, accepted (LEKA-381)."""
    found: dict[str, int] = {}
    for said in _said_of(provenance).values():
        origin = str(said.get("origin", "source"))
        found[origin] = found.get(origin, 0) + 1
    return found


def _disputed(provenance: object) -> tuple[str, ...]:
    """The attributes its sources disagree on, no one having settled them."""
    return tuple(
        sorted(name for name, said in _said_of(provenance).items() if said.get("disputed"))
    )


def _incident(entity: Entity, *, on: Entity | None, stated: bool) -> ChangeIncident:
    a = entity.attributes
    return ChangeIncident(
        entity=EntityBrief.model_validate(entity),
        opened_at=entity.occurred_at,
        severity=_said(a.get("severity")),
        state=_said(a.get("state")),
        on=EntityBrief.model_validate(on) if on is not None else None,
        stated=stated,
    )


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
