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
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from datetime import UTC, datetime, timedelta

from leka.connectors import ConnectorCategory, Source, manifests
from leka.ingestion.enrichment import twin, view
from leka.ingestion.enrichment.twin import IncidentSeen, SourceSeen, TwinState
from leka.ingestion.enrichment.view import Link, Thing
from leka.ingestion.models import ResolvedEntity
from leka.ingestion.repository import EnrichmentRepository
from leka.ingestion.schemas import (
    AttentionPointRead,
    EnrichedEntity,
    EntityActivityDay,
    EntityActivityEvent,
    EntityActivityRead,
    EntityRef,
    EntitySheetRead,
    EnvironmentEdgeRead,
    EnvironmentEventRead,
    EnvironmentNodeRead,
    EnvironmentRead,
    SheetLinkRead,
    SheetPersonRead,
    SheetTeamRead,
    TwinCoverageRead,
    TwinFreshnessRead,
    TwinIncidentRead,
    TwinSourceRead,
    TwinStateRead,
)

EVENTS = 6
SHEET_EVENTS = 8
OPEN_INCIDENTS_LISTED = 3
# What the view reads of enrichment.
# What a thing's state is read from — its health deduced from what runs it
# (`deduced_health`, enrichment's `architecture`) included: without it, a
# service nothing monitors was « non surveillé » here and « en bonne santé,
# déduit » on the architecture, the same service (2026-10-09).
FACTS = (
    "open_incidents",
    "lifecycle",
    "last_activity_at",
    "stale",
    "deduced_health",
    "last_deployment",
)
# The links the map draws, and the links a sheet lists.
MAP_LINKS = ("part_of", "depends_on", "owned_by", "in_network")
SHEET_LINKS = (
    "part_of",
    "depends_on",
    "owned_by",
    "in_network",
    "affects",
    "mentions",
    # A document is about it (LEKA-366): its documentation.
    "describes",
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
    # Where documents are kept, and the business: not something done
    # (LEKA-366).
    "knowledge_space",
    "business_capability",
    "business_process",
)


def monitoring_kinds() -> frozenset[str]:
    """The kinds of source that watch services run: PagerDuty, Datadog,
    Grafana, Splunk, Kibana — their connectors' category."""
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
    statuses, _ = await _states(repository, things, now)
    return statuses


async def _states(
    repository: EnrichmentRepository, things: dict[uuid.UUID, Thing], now: datetime
) -> tuple[dict[uuid.UUID, str | None], set[uuid.UUID]]:
    """Each thing's state — and those whose state is deduced from what runs
    them, no tool measuring it."""
    monitoring = monitoring_kinds()
    services = [t.id for t in things.values() if t.type == "service"]
    hit = await _hit_recently(repository, now, services)
    return (
        {
            thing.id: view.status(thing, monitoring=monitoring, recently_hit=thing.id in hit)
            for thing in things.values()
        },
        {
            thing.id
            for thing in things.values()
            if view.deduced(thing, monitoring=monitoring, recently_hit=thing.id in hit)
        },
    )


# ── the Digital Twin (LEKA-442) ───────────────────────────────────────────────


def sources_seen(rows: Iterable[Source]) -> list[SourceSeen]:
    """The workspace's sources, each with its connector's category and
    whether it receives what its system sends."""
    manifest = {m.key.value: m for m in manifests()}
    out: list[SourceSeen] = []
    for row in rows:
        kind = row.kind.value
        found = manifest.get(kind)
        error = row.last_error or {}
        out.append(
            SourceSeen(
                id=row.id,
                kind=kind,
                name=row.name,
                category=found.category.value if found else "custom",
                status=row.status.value,
                sync_status=row.sync_status.value,
                health=row.health_status.value,
                last_synced_at=row.last_synced_at,
                error=str(error.get("message") or error.get("code") or "") or None,
                webhooks=bool(found and found.receives),
            )
        )
    return out


async def twin_states(
    repository: EnrichmentRepository, things: dict[uuid.UUID, Thing], now: datetime
) -> tuple[dict[uuid.UUID, TwinState | None], list[SourceSeen], dict[uuid.UUID, set[uuid.UUID]]]:
    """Each thing's state in the twin, from the sources that show it and
    the open incidents on it — and the sources, and which show what."""
    seen = sources_seen(await repository.workspace_sources())
    by_id = {s.id: s for s in seen}
    stateful = [t.id for t in things.values() if t.type in twin.HAS_STATE]
    of = await repository.sources_of(stateful)
    open_ids = list(await repository.open_incidents())
    incidents = await _things(repository, ids=open_ids)
    on: dict[uuid.UUID, list[IncidentSeen]] = defaultdict(list)
    for from_id, to_id, _ in await repository.links_of(open_ids, ["affects"]):
        incident = incidents.get(from_id)
        if incident is None:
            continue
        severity = incident.attributes.get("severity") or incident.attributes.get("priority")
        on[to_id].append(
            IncidentSeen(
                incident.id, incident.key, incident.name, str(severity) if severity else None
            )
        )
    monitoring = any(s.connected and s.category == "observability" for s in seen)
    states = {
        thing_id: twin.state_of(
            things[thing_id],
            sources=[by_id[i] for i in sorted(of.get(thing_id, ()), key=str) if i in by_id],
            incidents=on.get(thing_id, []),
            monitoring_connected=monitoring,
            now=now,
        )
        for thing_id in stateful
    }
    return states, seen, of


async def twin_now(
    repository: EnrichmentRepository, now: datetime
) -> tuple[dict[uuid.UUID, Thing], dict[uuid.UUID, TwinState | None], list[SourceSeen]]:
    """Every thing with a state, its state now, and the sources — what the
    monitoring sweep watches (leka.monitoring)."""
    things = await _things(repository, types=sorted(twin.HAS_STATE))
    states, seen, _ = await twin_states(repository, things, now)
    return things, states, seen


def twin_read(found: TwinState | None) -> TwinStateRead | None:
    if found is None:
        return None
    incident = found.incident
    return TwinStateRead(
        state=found.state,
        basis=found.basis,
        reason=found.reason,
        observed_at=found.observed_at,
        signal=list(found.signal),
        fresh=found.fresh,
        was=found.was,
        certainty=found.certainty,
        incident=TwinIncidentRead(
            id=incident.id, key=incident.key, name=incident.name, severity=incident.severity
        )
        if incident is not None
        else None,
    )


def source_read(source: SourceSeen, now: datetime) -> TwinSourceRead:
    return TwinSourceRead(
        id=source.id,
        kind=source.kind,
        name=source.name,
        category=source.category,
        state=source.state(now),
        last_synced_at=source.last_synced_at,
        error=source.error,
        webhooks=source.webhooks,
    )


def external(thing: Thing) -> bool:
    """A service the company uses and does not run — an e-mail provider, a
    payment API: on the architecture's « Dépendances externes »."""
    return thing.type == "service" and thing.attributes.get("hosting") == "external"


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
    statuses, deduced = await _states(repository, things, now)
    twins, seen, _ = await twin_states(repository, things, now)
    # A provider's box: the worst of its resources' states.
    boxes: dict[str, list[TwinState]] = defaultdict(list)
    for thing in things.values():
        found = twins.get(thing.id)
        if thing.type == "infra_resource" and found is not None and (at := view.provider_of(thing)):
            boxes[f"provider:{at[0]}:{at[1] or ''}"].append(found)
    links = [
        Link(a, b, kind) for a, b, kind in await repository.links_among(view.MAP_TYPES, MAP_LINKS)
    ]
    nodes, edges, layers = view.layout(things.values(), links, statuses)
    teams = {t.id: t for t in things.values() if t.type == "team"}

    # Counted as the architecture counts them: the company's own, the
    # external ones apart.
    services = [t for t in things.values() if t.type == "service" and not external(t)]
    outside = [t for t in things.values() if external(t)]
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
                twin=twin_read(
                    twins.get(node.entity_id)
                    if node.entity_id is not None
                    else max(
                        boxes.get(node.id, []), key=lambda f: twin.WORST[f.state], default=None
                    )
                ),
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
        services_deduced=sum(1 for s in services if s.id in deduced),
        services_unknown=sum(1 for s in services if statuses.get(s.id) == "unmonitored"),
        services_external=len(outside),
        incidents_open=len(open_incidents),
        services_impacted=len(impacted),
        changes_24h=len(changes),
        attention=await _attention(repository, things, statuses, open_incidents, deduced),
        events=await _events(repository, moved),
        states=twin.counted(twins),
        freshness=_freshness(seen, now),
        coverage=[
            TwinCoverageRead(
                part=part.part,
                covered=part.covered,
                sources=[s.id for s in part.sources],
            )
            for part in twin.coverage(seen)
        ],
        sources=[source_read(s, now) for s in seen],
    )


def _freshness(seen: Sequence[SourceSeen], now: datetime) -> TwinFreshnessRead:
    found = twin.freshness(seen, now)
    return TwinFreshnessRead(
        last_read_at=found.last_read_at,
        every_minutes=int(found.every.total_seconds() // 60),
        late=found.late,
        webhooks=found.webhooks,
    )


async def _attention(
    repository: EnrichmentRepository,
    things: dict[uuid.UUID, Thing],
    statuses: dict[uuid.UUID, str | None],
    open_incidents: Sequence[uuid.UUID],
    deduced: Collection[uuid.UUID] = (),
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
        # What no tool measures — its state deduced from what runs it, or
        # not known at all: worth knowing, not alarming.
        (
            "unmonitored_services",
            "info",
            sum(
                1
                for t in things.values()
                if t.type == "service"
                and not external(t)
                and (statuses.get(t.id) == "unmonitored" or t.id in deduced)
            ),
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


async def _around(
    repository: EnrichmentRepository, this: Thing, others: dict[uuid.UUID, Thing]
) -> list[uuid.UUID]:
    """What is part of a thing or affects it — and, for a service, what is
    part of its repositories: where its activity is."""
    around = [other_id for other_id, other in others.items() if other.type not in NOT_EVENTS]
    if this.type == "service":
        repositories = [o.id for o in others.values() if o.type == "repository"]
        around += [
            a
            for a, b, _ in await repository.links_of(repositories, ["part_of"])
            if b in repositories
        ]
    return around


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
    statuses, deduced = await _states(repository, {**others, this.id: this}, now)
    twins, seen, of = await twin_states(repository, {this.id: this}, now)
    shown_by = of.get(this.id, set())
    if not shown_by:
        shown_by = set((await repository.sources_of([this.id])).get(this.id, set()))
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
    around = await _around(repository, this, others)
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
    if statuses.get(this.id) == "unmonitored" or this.id in deduced:
        attention.append(
            AttentionPointRead(
                kind="unmonitored_services", level="info", count=1, entity=None, detail=None
            )
        )

    environment = this.attributes.get("environment")
    return EntitySheetRead(
        entity=enriched,
        status=statuses.get(this.id),
        deduced=this.id in deduced,
        environment=environment if isinstance(environment, str) else None,
        owner=owner,
        team=team,
        incidents=incidents,
        events=await _events(repository, moved),
        dependencies=sorted(dependencies, key=lambda d: (d.type, d.entity.name)),
        documents=sorted(documents, key=lambda d: d.name),
        attention=attention,
        source_kinds=sorted(this.kinds),
        twin=twin_read(twins.get(this.id)),
        sources=[source_read(s, now) for s in seen if s.id in shown_by],
    )


# ── one thing's activity ─────────────────────────────────────────────────────

ACTIVITY_LIMIT = 1000
CHANGE_TYPES = frozenset({"commit", "pull_request"})
DEPLOY_TYPES = frozenset({"deployment", "release"})
WORK_TYPES = frozenset({"issue"})


def _bucket(event: EntityActivityEvent) -> str:
    kind = event.entity.type
    if kind in CHANGE_TYPES:
        return "changes"
    if kind in DEPLOY_TYPES:
        return "deployments"
    if kind == "incident":
        return "incidents"
    if kind in WORK_TYPES:
        return "work"
    return "other"


def _said(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


async def activity(
    repository: EnrichmentRepository, entity: ResolvedEntity, *, now: datetime, days: int
) -> EntityActivityRead:
    """Everything that moved around one thing over `days` — and over the
    `days` before, counted — its incidents included; each as its source
    says it: its state, its link, its version, its environment."""
    this = (await _things(repository, ids=[entity.id]))[entity.id]
    links = [
        (a, b, kind)
        for a, b, kind in await repository.links_of([entity.id], SHEET_LINKS)
        if entity.id in (a, b)
    ]
    others = await _things(repository, ids=[b if a == entity.id else a for a, b, _ in links])
    around = await _around(repository, this, others)
    around += [o.id for o in others.values() if o.type == "incident"]
    start = now - timedelta(days=days)
    before = now - timedelta(days=2 * days)
    moved = await repository.moved_since(
        _iso(before), among=around, exclude=NOT_EVENTS, limit=ACTIVITY_LIMIT
    )
    things = await _things(repository, ids=[entity_id for entity_id, _ in moved])
    events: list[EntityActivityEvent] = []
    earlier: dict[str, int] = defaultdict(int)
    for event in await _events(repository, moved):
        thing = things.get(event.entity.id)
        attributes = thing.attributes if thing else {}
        full = EntityActivityEvent(
            **event.model_dump(),
            state=_said(attributes.get("state")),
            url=_said(attributes.get("url")),
            version=_said(attributes.get("version")) or _said(attributes.get("tag")),
            environment=_said(attributes.get("environment")),
        )
        if event.at >= _iso(start):
            events.append(full)
        else:
            earlier[_bucket(full)] += 1
    counts: dict[str, dict[str, int]] = {
        (start + timedelta(days=n + 1)).date().isoformat(): defaultdict(int) for n in range(days)
    }
    for event in events:
        day = counts.get(event.at[:10])
        if day is not None:
            day[_bucket(event)] += 1
    total: dict[str, int] = defaultdict(int)
    for event in events:
        total[_bucket(event)] += 1
    observability = monitoring_kinds()
    return EntityActivityRead(
        days=days,
        since=_iso(start),
        events=events,
        by_day=[
            EntityActivityDay(
                day=day,
                changes=c["changes"],
                deployments=c["deployments"],
                incidents=c["incidents"],
                work=c["work"],
                other=c["other"],
            )
            for day, c in counts.items()
        ],
        changes=total["changes"],
        deployments=total["deployments"],
        incidents=total["incidents"],
        incidents_open=sum(1 for e in events if e.kind == "incident"),
        work=total["work"],
        work_open=sum(
            1
            for e in events
            if e.entity.type in WORK_TYPES and (e.state or "") in ("open", "in_progress")
        ),
        last_activity=events[0].at if events else None,
        previous={k: earlier[k] for k in ("changes", "deployments", "incidents", "work")},
        log_sources=sorted(await repository.connected_kinds() & observability),
        mentions=await _mentions(repository, this, linked=set(others)),
    )


async def _mentions(
    repository: EnrichmentRepository, this: Thing, *, linked: set[uuid.UUID]
) -> list[EntityRef]:
    """The documents that name it — a name too short to search says
    nothing — not those already linked as its documentation."""
    if len(this.name.strip()) < 4:
        return []
    return [
        EntityRef(id=entity_id, type=kind, key=key, name=name)
        for entity_id, kind, key, name, _ in await repository.mentioning(
            this.name.strip(), types=["document"]
        )
        if entity_id not in linked and entity_id != this.id
    ]
