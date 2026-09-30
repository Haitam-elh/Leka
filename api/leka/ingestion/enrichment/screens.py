"""The "Mon environnement" screens' data (LEKA-359, mockups 10 and 11): read
from what resolution and enrichment made, put together by view.py's rules.

    environment()   the workspace: its map, its figures, what needs
                    attention, what moved last
    sheet()         one entity: its state, owner and team, its incidents,
                    events, dependencies and documents

Read-only, and read at each call: a few queries over one workspace's
resolved entities, their enrichment and their relationships.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from leka.connectors import ConnectorCategory, manifests
from leka.ingestion.enrichment import view
from leka.ingestion.enrichment.view import Link, Thing
from leka.ingestion.models import ResolvedEntity
from leka.ingestion.repository import EnrichmentRepository
from leka.ingestion.schemas import (
    AttentionPointRead,
    EnrichedEntity,
    EntityRef,
    EntitySheetRead,
    EnvironmentEdgeRead,
    EnvironmentEventRead,
    EnvironmentNodeRead,
    EnvironmentRead,
    SheetLinkRead,
    SheetPersonRead,
    SheetTeamRead,
)

EVENTS = 6
SHEET_EVENTS = 8
OPEN_INCIDENTS_LISTED = 3
# What the view reads of enrichment.
FACTS = ("open_incidents", "lifecycle", "last_activity_at", "stale")
# The links the map draws, and the links a sheet lists.
MAP_LINKS = ("part_of", "depends_on", "owned_by", "in_network")
SHEET_LINKS = (
    "part_of",
    "depends_on",
    "owned_by",
    "in_network",
    "affects",
    "mentions",
    "maintained_by",
    "member_of",
)
CONTAINERS = ("service", "repository", "project")
# What is not an event: containers, people — and databases and cloud
# resources, whose last change is a state read again, not something done.
NOT_EVENTS = (
    "service",
    "application",
    "environment",
    "repository",
    "project",
    "team",
    "person",
    "database",
    "infra_resource",
)


def monitoring_kinds() -> frozenset[str]:
    """The kinds of source that watch services run: PagerDuty, Datadog,
    Grafana — their connectors' category."""
    return frozenset(
        m.key.value for m in manifests() if m.category is ConnectorCategory.OBSERVABILITY
    )


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _things(
    repository: EnrichmentRepository,
    *,
    types: Sequence[str] | None = None,
    ids: Sequence[uuid.UUID] | None = None,
) -> dict[uuid.UUID, Thing]:
    rows = await repository.things(types=types, ids=ids)
    entity_ids = [row[0] for row in rows]
    facts = await repository.facts_of(entity_ids, FACTS)
    kinds = await repository.kinds_of(entity_ids)
    return {
        entity_id: Thing(
            id=entity_id,
            type=kind,
            key=key,
            name=name,
            attributes=attributes or {},
            facts=facts.get(entity_id, {}),
            kinds=frozenset(kinds.get(entity_id, ())),
        )
        for entity_id, kind, key, name, attributes in rows
    }


def _ref(thing: Thing) -> EntityRef:
    return EntityRef(id=thing.id, type=thing.type, key=thing.key, name=thing.name)


async def _hit_recently(
    repository: EnrichmentRepository, now: datetime, services: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """The services an incident affecting them moved in the last 7 days."""
    since = _iso(now - view.RECENT_INCIDENT)
    incidents = [i for i, _ in await repository.moved_since(since, types=["incident"])]
    wanted = set(services)
    return {
        to_id
        for from_id, to_id, _ in await repository.links_of(incidents, ["affects"])
        if from_id in incidents and to_id in wanted
    }


async def _statuses(
    repository: EnrichmentRepository, things: dict[uuid.UUID, Thing], now: datetime
) -> dict[uuid.UUID, str | None]:
    monitoring = monitoring_kinds()
    services = [t.id for t in things.values() if t.type == "service"]
    hit = await _hit_recently(repository, now, services)
    return {
        thing.id: view.status(thing, monitoring=monitoring, recently_hit=thing.id in hit)
        for thing in things.values()
    }


async def _events(
    repository: EnrichmentRepository, moved: Sequence[tuple[uuid.UUID, str]]
) -> list[EnvironmentEventRead]:
    """What moved, each with where it belongs: the service it affects or is
    part of, else its repository, else its project."""
    ids = [entity_id for entity_id, _ in moved]
    things = await _things(repository, ids=ids)
    links = await repository.links_of(ids, ["part_of", "affects"])
    around = {to_id for from_id, to_id, _ in links if from_id in things}
    containers = {
        entity_id: thing
        for entity_id, thing in (await _things(repository, ids=list(around))).items()
        if thing.type in CONTAINERS
    }
    where: dict[uuid.UUID, Thing] = {}
    for from_id, to_id, _ in links:
        container = containers.get(to_id)
        if container is None or from_id not in things:
            continue
        held = where.get(from_id)
        if held is None or CONTAINERS.index(container.type) < CONTAINERS.index(held.type):
            where[from_id] = container
    return [
        EnvironmentEventRead(
            entity=_ref(things[entity_id]),
            at=at,
            kind=view.event_kind(things[entity_id]),
            where=_ref(where[entity_id]) if entity_id in where else None,
            source_kinds=sorted(things[entity_id].kinds),
        )
        for entity_id, at in moved
        if entity_id in things
    ]


# ── the workspace ────────────────────────────────────────────────────────────


async def environment(repository: EnrichmentRepository, *, now: datetime) -> EnvironmentRead:
    things = await _things(repository, types=view.MAP_TYPES)
    statuses = await _statuses(repository, things, now)
    links = [
        Link(a, b, kind) for a, b, kind in await repository.links_among(view.MAP_TYPES, MAP_LINKS)
    ]
    nodes, edges, layers = view.layout(things.values(), links, statuses)
    teams = {t.id: t for t in things.values() if t.type == "team"}

    services = [t for t in things.values() if t.type == "service"]
    open_incidents = list(await repository.open_incidents())
    impacted = {
        to_id
        for from_id, to_id, _ in await repository.links_of(open_incidents, ["affects"])
        if from_id in open_incidents
    }
    changes = await repository.moved_since(
        _iso(now - view.CHANGE_WINDOW), types=sorted(view.CHANGES)
    )
    moved = await repository.moved_since("", exclude=NOT_EVENTS, limit=EVENTS)

    return EnvironmentRead(
        updated_at=await repository.finished_at(),
        nodes=[
            EnvironmentNodeRead(
                id=node.id,
                type=node.type,
                layer=node.layer,
                name=node.name,
                status=node.status,
                entity_id=node.entity_id,
                key=node.key,
                detail=node.detail,
                count=node.count,
                environment=node.environment,
                team=_ref(teams[node.team_id]) if node.team_id in teams else None,
            )
            for node in nodes
        ],
        edges=[
            EnvironmentEdgeRead(from_id=e.from_id, to_id=e.to_id, type=e.type, status=e.status)
            for e in edges
        ],
        layers=layers,
        environments=sorted({n.environment for n in nodes if n.environment}),
        services=len(services),
        services_operational=sum(1 for s in services if statuses.get(s.id) == "operational"),
        incidents_open=len(open_incidents),
        services_impacted=len(impacted),
        changes_24h=len(changes),
        attention=await _attention(repository, things, statuses, open_incidents),
        events=await _events(repository, moved),
    )


async def _attention(
    repository: EnrichmentRepository,
    things: dict[uuid.UUID, Thing],
    statuses: dict[uuid.UUID, str | None],
    open_incidents: Sequence[uuid.UUID],
) -> list[AttentionPointRead]:
    """What needs attention, the most urgent first: the open incidents,
    resources failed or stopped, work left waiting, services nothing
    watches, repositories nobody touches."""
    points: list[AttentionPointRead] = []
    incidents = await _things(repository, ids=list(open_incidents)[:OPEN_INCIDENTS_LISTED])
    affected = await repository.links_of(list(incidents), ["affects"])
    for incident in incidents.values():
        names = sorted(
            things[to_id].name
            for from_id, to_id, _ in affected
            if from_id == incident.id and to_id in things
        )
        points.append(
            AttentionPointRead(
                kind="open_incident",
                level="high",
                count=1,
                entity=_ref(incident),
                detail=", ".join(names) or None,
            )
        )
    resources = [t for t in things.values() if t.type in ("database", "infra_resource")]
    counted = [
        ("failed_resources", "high", sum(1 for r in resources if statuses[r.id] == "incident")),
        ("stopped_resources", "medium", sum(1 for r in resources if statuses[r.id] == "attention")),
        ("stale_work", "medium", await repository.count_where("stale", True)),
        (
            "unmonitored_services",
            "info",
            sum(1 for t in things.values() if statuses.get(t.id) == "unmonitored"),
        ),
        (
            "dormant_repositories",
            "info",
            sum(
                1
                for t in things.values()
                if t.type == "repository" and t.facts.get("lifecycle") == "dormant"
            ),
        ),
    ]
    points += [
        AttentionPointRead(kind=kind, level=level, count=count, entity=None, detail=None)
        for kind, level, count in counted
        if count
    ]
    return points


# ── one entity ───────────────────────────────────────────────────────────────


async def sheet(
    repository: EnrichmentRepository,
    entity: ResolvedEntity,
    enriched: EnrichedEntity,
    *,
    now: datetime,
) -> EntitySheetRead:
    this = (await _things(repository, ids=[entity.id]))[entity.id]
    links = [
        (a, b, kind)
        for a, b, kind in await repository.links_of([entity.id], SHEET_LINKS)
        if entity.id in (a, b)
    ]
    others = await _things(repository, ids=[b if a == entity.id else a for a, b, _ in links])
    statuses = await _statuses(repository, {**others, this.id: this}, now)
    edges = {(e.from_entity.id, e.to_entity.id, e.type): e for e in enriched.outgoing}
    edges |= {(e.from_entity.id, e.to_entity.id, e.type): e for e in enriched.incoming}

    owner = team = None
    maintainers = [e for e in enriched.outgoing if e.type == "maintained_by"]
    if maintainers:
        best = max(maintainers, key=lambda e: e.confidence)
        owner = SheetPersonRead(
            entity=best.to_entity, confidence=best.confidence, evidence=best.evidence
        )
    owners = [e for e in enriched.outgoing if e.type == "owned_by" and e.to_entity.type == "team"]
    if owners:
        best = max(owners, key=lambda e: (e.origin == "stated", e.confidence))
        members = await repository.links_of([best.to_entity.id], ["member_of"])
        team = SheetTeamRead(
            entity=best.to_entity,
            confidence=best.confidence,
            origin=best.origin,
            members=len({a for a, b, _ in members if b == best.to_entity.id}),
        )

    dependencies: list[SheetLinkRead] = []
    documents: list[EntityRef] = []
    incident_ids: list[uuid.UUID] = []
    for a, b, kind in links:
        other_id = b if a == entity.id else a
        other = others.get(other_id)
        edge = edges.get((a, b, kind))
        if other is None or edge is None:
            continue
        if other.type == "incident" and kind == "affects":
            incident_ids.append(other.id)
        elif other.type == "document":
            documents.append(_ref(other))
        elif other.type in (*view.LAYERS, "project") and kind not in ("maintained_by", "member_of"):
            dependencies.append(
                SheetLinkRead(
                    entity=_ref(other),
                    type=kind,
                    direction="out" if a == entity.id else "in",
                    status=statuses.get(other.id),
                    origin=edge.origin,
                    confidence=edge.confidence,
                    cross_source=edge.cross_source,
                )
            )

    # What moved around it: what is part of it or affects it — and, for a
    # service, what is part of its repositories.
    around = [other_id for other_id, other in others.items() if other.type not in NOT_EVENTS]
    if this.type == "service":
        repositories = [o.id for o in others.values() if o.type == "repository"]
        around += [
            a
            for a, b, _ in await repository.links_of(repositories, ["part_of"])
            if b in repositories
        ]
    moved = await repository.moved_since("", among=around, exclude=NOT_EVENTS, limit=SHEET_EVENTS)
    incidents_moved = await repository.moved_since("", among=incident_ids, limit=SHEET_EVENTS)
    incidents = await _events(repository, incidents_moved)
    incidents.sort(key=lambda e: e.kind != "incident")  # the open ones first

    attention = [
        AttentionPointRead(
            kind="open_incident", level="high", count=1, entity=i.entity, detail=this.name
        )
        for i in incidents
        if i.kind == "incident"
    ]
    stale = sum(1 for o in others.values() if o.facts.get("stale") is True)
    if stale:
        attention.append(
            AttentionPointRead(
                kind="stale_work", level="medium", count=stale, entity=None, detail=None
            )
        )
    if statuses.get(this.id) == "unmonitored":
        attention.append(
            AttentionPointRead(
                kind="unmonitored_services", level="info", count=1, entity=None, detail=None
            )
        )

    environment = this.attributes.get("environment")
    return EntitySheetRead(
        entity=enriched,
        status=statuses.get(this.id),
        environment=environment if isinstance(environment, str) else None,
        owner=owner,
        team=team,
        incidents=incidents,
        events=await _events(repository, moved),
        dependencies=sorted(dependencies, key=lambda d: (d.type, d.entity.name)),
        documents=sorted(documents, key=lambda d: d.name),
        attention=attention,
        source_kinds=sorted(this.kinds),
    )
