"""LEKA's reads, as skills (LEKA-396): what LEKA knows of a company, each
read one skill — its contract, its permission — run through the skill
runtime (capabilities/skills.py): checked, read only, kept. LEKA's analyst
reads through them (analyst.py); the agents and the workflows will.

    find           things by name or words
    describe       one thing: what it is, its state, owners, ties, sources
    dependencies   what it depends on, what depends on it
    happened       what happened in a period — deployments, merges,
                   releases, changes, incidents — everywhere, in one
                   environment, or around one thing
    incident       one incident: what it reached, what caused it
    learned        what LEKA's model gained, changed, lost in a period
    sources        what LEKA reads, and when it last read it
    insights       what LEKA already concluded and is still open
    overview       what the model holds: how many of each kind

Each says what it read, as it can be cited (`cited`): the evidence an
answer rests on. Each gives a short answer: MOST things at most, LONGEST
characters of any text.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import (
    Call,
    Cited,
    CitedSource,
    Citing,
    Skill,
    UnknownThingError,
    register,
)
from leka.connectors import Source
from leka.governance import Permission
from leka.intelligence import IntelligenceRepository
from leka.intentions.reads import HAPPENINGS, in_environment, learned_between
from leka.knowledge import (
    Entity,
    EntityBrief,
    EntityRepository,
    EntityType,
    EvolutionRepository,
    GraphRepository,
    GraphService,
    KnowledgeService,
    Lifecycle,
    RelationshipType,
)

# What one read gives, at most.
MOST = 25
LONGEST = 300
# The period read when none is said: the week before.
WEEK = timedelta(days=7)

EVENTS = (
    EntityType.DEPLOYMENT,
    EntityType.PULL_REQUEST,
    EntityType.RELEASE,
    EntityType.CHANGE,
    EntityType.INCIDENT,
)
# What a thing's attributes say that is worth telling.
SAID = (
    "description",
    "summary",
    "status",
    "state",
    "version",
    "criticality",
    "environment",
    "environments",
    "url",
    "language",
    "languages",
    "runtime",
    "framework",
    "region",
    "provider",
    "engine",
    "instance_type",
    "ref",
    "commit",
    "author",
    "severity",
    "priority",
    "visibility",
    "default_branch",
    "topics",
    "freshness",
    "size",
)
KINDS = frozenset(kind.value for kind in EntityType)


# ── what they share ──────────────────────────────────────────────────────────


def cut(text: object, longest: int = LONGEST) -> str | None:
    if text is None:
        return None
    said = str(text)
    return said if len(said) <= longest else said[: longest - 1] + "…"


def id_of(said: object) -> uuid.UUID | None:
    """The thing an id names — « entity:… », « event:… », or the uuid alone."""
    text = str(said or "").strip()
    if ":" in text:
        text = text.split(":", 1)[1]
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def _kinds(asked: Iterable[str]) -> list[EntityType]:
    """The kinds asked for, as LEKA names them — what was made up, left out."""
    return [EntityType(kind) for kind in asked if kind in KINDS]


def _type(entity: Entity | EntityBrief) -> str:
    return entity.type.value if hasattr(entity.type, "value") else str(entity.type)


def _said(attributes: Mapping[str, object]) -> dict[str, Any]:
    """What a thing's attributes say worth telling, short."""
    told: dict[str, Any] = {}
    for key in SAID:
        value = attributes.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            told[key] = [cut(v, 80) for v in value[:8]]
        elif isinstance(value, (str, int, float, bool)):
            told[key] = cut(value) if isinstance(value, str) else value
    return told


Sources = Mapping[uuid.UUID, tuple[CitedSource, ...]]


async def _sources_of(
    session: AsyncSession, workspace_id: uuid.UUID, entities: Iterable[Entity]
) -> dict[uuid.UUID, tuple[CitedSource, ...]]:
    """Each thing's sources, by its provenance."""
    rows = await session.execute(
        select(Source.id, Source.kind, Source.name).where(Source.workspace_id == workspace_id)
    )
    named = {ident: (kind.value, name) for ident, kind, name in rows.tuples().all()}
    found: dict[uuid.UUID, tuple[CitedSource, ...]] = {}
    for entity in entities:
        said = (entity.provenance or {}).get("sources") or []
        refs: dict[uuid.UUID, CitedSource] = {}
        for item in said if isinstance(said, list) else []:
            source = id_of(item.get("source_id") if isinstance(item, dict) else None)
            if source is not None:
                kind, name = named.get(source, (None, None))
                refs[source] = CitedSource(id=source, kind=kind, name=name)
        found[entity.id] = tuple(refs.values())
    return found


class Reading:
    """What one read read, by the id it may be cited by."""

    def __init__(self) -> None:
        self.read: dict[str, Cited] = {}

    def keep(self, cited: Cited) -> str:
        self.read.setdefault(cited.id, cited)
        return cited.id

    def entity(
        self,
        thing: Entity | EntityBrief,
        sources: Sources,
        *,
        detail: str | None = None,
        at: datetime | None = None,
    ) -> str:
        kind = _type(thing)
        happening = EntityType(kind) in HAPPENINGS
        return self.keep(
            Cited(
                id=f"{'event' if happening else 'entity'}:{thing.id}",
                kind="event" if happening else "entity",
                label=thing.name,
                ref_type=kind,
                ref_id=thing.id,
                sources=list(sources.get(thing.id, ())),
                detail=cut(detail),
                at=at,
            )
        )

    @property
    def cited(self) -> list[Cited]:
        return list(self.read.values())


def _period(since: datetime | None, until: datetime | None, now: datetime) -> tuple[datetime, ...]:
    end = until or now
    start = since or end - WEEK
    return min(start, end), max(start, end)


ID = "An id as a read gave it: « entity:… » or « event:… »."
AN_ID = "one thing, by an id as a read gave it: « entity:… » or « event:… »."
TYPES = (
    "Kinds to keep: service, application, repository, database, infra_resource, team, person, "
    "document…"
)


class Thing(BaseModel):
    id: str
    name: str
    type: str


# ── find ─────────────────────────────────────────────────────────────────────


class FindAsked(BaseModel):
    query: str = Field(max_length=200, description="A name, or words.")
    types: list[str] = Field(default_factory=list, max_length=20, description=TYPES)


class Found(Thing):
    lifecycle: str
    within: str | None = Field(description="What it is part of, a child or a member of.")


class FindSaid(Citing):
    found: list[Found]


async def find(asked: FindAsked, call: Call) -> FindSaid:
    reading = Reading()
    graph = GraphService(GraphRepository(call.session, call.workspace_id))
    found = await graph.search(asked.query.strip(), types=_kinds(asked.types), limit=MOST)
    entities = await EntityRepository(call.session, call.workspace_id).by_ids(
        [hit.entity.id for hit in found.entities]
    )
    sources = await _sources_of(call.session, call.workspace_id, entities.values())
    return FindSaid(
        found=[
            Found(
                id=reading.entity(hit.entity, sources),
                name=hit.entity.name,
                type=_type(hit.entity),
                lifecycle=hit.entity.lifecycle.value,
                within=hit.holder.name if hit.holder else None,
            )
            for hit in found.entities
        ],
        cited=reading.cited,
    )


# ── describe ─────────────────────────────────────────────────────────────────


class OneAsked(BaseModel):
    id: str = Field(max_length=100, description=ID)


class Answerer(BaseModel):
    name: str
    type: str | None = None
    said: str | None = Field(default=None, description="stated, inferred, accepted.")


class Responsible(BaseModel):
    owners: list[Answerer]
    leads: list[str]
    maintainers: list[Answerer]
    experts: list[str]
    escalation: str | None


class Tied(BaseModel):
    relation: str
    direction: Literal["to", "from"]
    other: Thing
    said: str


class SourceSaid(BaseModel):
    id: str
    kind: str | None
    name: str | None


class Described(Citing):
    id: str
    name: str
    type: str
    lifecycle: str
    attributes: dict[str, Any]
    happened_at: datetime | None
    responsibility: Responsible
    ties: list[Tied]
    sources: list[SourceSaid]


async def _entity(call: Call, said: str) -> tuple[EntityRepository, Entity]:
    repository = EntityRepository(call.session, call.workspace_id)
    ident = id_of(said)
    entity = (await repository.by_ids([ident])).get(ident) if ident else None
    if entity is None:
        raise UnknownThingError("LEKA knows no such thing.")
    return repository, entity


async def describe(asked: OneAsked, call: Call) -> Described:
    reading = Reading()
    repository, entity = await _entity(call, asked.id)
    graph = GraphRepository(call.session, call.workspace_id)
    # Who answers for it as LEKA reads it everywhere (LEKA-365): owners,
    # maintainers, leads, who knows it — said or inferred.
    held = await KnowledgeService(repository).responsibility(entity)
    edges = await graph.around([entity.id], list(RelationshipType))
    others = await repository.by_ids(
        [e.to_entity_id if e.from_entity_id == entity.id else e.from_entity_id for e in edges]
    )
    sources = await _sources_of(call.session, call.workspace_id, [entity, *others.values()])
    ties: list[Tied] = []
    for edge in sorted(edges, key=lambda e: -e.confidence):
        outgoing = edge.from_entity_id == entity.id
        other = others.get(edge.to_entity_id if outgoing else edge.from_entity_id)
        if other is None or other.lifecycle is Lifecycle.REMOVED:
            continue
        ties.append(
            Tied(
                relation=edge.type.value,
                direction="to" if outgoing else "from",
                other=Thing(id=reading.entity(other, sources), name=other.name, type=_type(other)),
                said=edge.origin,
            )
        )
        if len(ties) == MOST * 2:
            break
    return Described(
        id=reading.entity(entity, sources, at=entity.occurred_at),
        name=entity.name,
        type=_type(entity),
        lifecycle=entity.lifecycle.value,
        attributes=_said(entity.attributes or {}),
        happened_at=entity.occurred_at,
        responsibility=Responsible(
            owners=[
                Answerer(name=t.entity.name, type=_type(t.entity), said=t.origin)
                for t in held.owners
            ],
            leads=[lead.name for lead in held.leads],
            maintainers=[Answerer(name=t.entity.name, said=t.origin) for t in held.maintainers],
            experts=[t.entity.name for t in held.experts[:5]],
            escalation=held.escalation_policy,
        ),
        ties=ties,
        sources=[
            SourceSaid(id=f"source:{s.id}", kind=s.kind, name=s.name)
            for s in sources.get(entity.id, ())
        ],
        cited=reading.cited,
    )


# ── dependencies ─────────────────────────────────────────────────────────────


class DependenciesAsked(BaseModel):
    id: str = Field(max_length=100, description=ID)
    direction: Literal["downstream", "upstream"] = Field(
        description="downstream: what it depends on; upstream: what depends on it."
    )
    environment: str | None = Field(
        default=None, max_length=50, description="Only what runs there: production, staging…"
    )


class Dependency(Thing):
    steps: int
    criticality: str | None


class DependenciesSaid(Citing):
    of: str
    direction: Literal["downstream", "upstream"]
    things: list[Dependency]
    more: bool


async def dependencies(asked: DependenciesAsked, call: Call) -> DependenciesSaid:
    reading = Reading()
    ident = id_of(asked.id)
    repository = EntityRepository(call.session, call.workspace_id)
    found = (
        await KnowledgeService(repository).dependencies(
            ident, direction=asked.direction, depth=2, environment=asked.environment
        )
        if ident is not None
        else None
    )
    if found is None:
        raise UnknownThingError("LEKA knows no such thing.")
    nodes = found.nodes[:MOST]
    entities = await repository.by_ids([n.entity.id for n in nodes])
    sources = await _sources_of(call.session, call.workspace_id, entities.values())
    return DependenciesSaid(
        of=found.root.name,
        direction=asked.direction,
        things=[
            Dependency(
                id=reading.entity(node.entity, sources),
                name=node.entity.name,
                type=_type(node.entity),
                steps=node.depth,
                criticality=node.criticality,
            )
            for node in nodes
        ],
        more=found.truncated or len(found.nodes) > MOST,
        cited=reading.cited,
    )


# ── happened ─────────────────────────────────────────────────────────────────


class Period(BaseModel):
    since: datetime | None = Field(
        default=None, description="ISO 8601 date-time, the start — a week before the end if none."
    )
    until: datetime | None = Field(default=None, description="ISO 8601 date-time, the end — now.")

    @field_validator("since", "until")
    @classmethod
    def _zoned(cls, moment: datetime | None) -> datetime | None:
        """A moment said without its zone: UTC."""
        return moment.replace(tzinfo=UTC) if moment and moment.tzinfo is None else moment


class HappenedAsked(Period):
    environment: str | None = Field(
        default=None, max_length=50, description="Only there: production, staging…"
    )
    around: str | None = Field(default=None, max_length=100, description=f"Only around {AN_ID}")


class Happening(BaseModel):
    id: str
    what: str
    name: str
    at: datetime
    state: str | None
    environment: str | None
    on: str | None
    details: dict[str, Any]


class HappenedSaid(Citing):
    since: datetime
    until: datetime
    around: str | None
    environment: str | None
    events: list[Happening]
    more: bool


async def happened(asked: HappenedAsked, call: Call) -> HappenedSaid:
    reading = Reading()
    since, until = _period(asked.since, asked.until, call.now)
    repository = EntityRepository(call.session, call.workspace_id)
    entity = None
    if asked.around:
        _, entity = await _entity(call, asked.around)
    timeline = await KnowledgeService(repository).timeline(
        entity, since=since, until=until, kinds=list(EVENTS), limit=MOST * 2
    )
    environment = asked.environment or None
    events = [e for e in timeline.events if in_environment(e.environment, environment)][: MOST * 2]
    entities = await repository.by_ids([e.entity.id for e in events])
    sources = await _sources_of(call.session, call.workspace_id, entities.values())
    said: list[Happening] = []
    for event in events:
        thing = entities.get(event.entity.id)
        said.append(
            Happening(
                id=reading.entity(event.entity, sources, detail=event.kind, at=event.at),
                what=event.kind,
                name=event.entity.name,
                at=event.at,
                state=event.state,
                environment=event.environment,
                on=event.via.name if event.via else None,
                details=_said(thing.attributes or {}) if thing else {},
            )
        )
    return HappenedSaid(
        since=since,
        until=until,
        around=entity.name if entity else None,
        environment=environment,
        events=said,
        more=timeline.truncated,
        cited=reading.cited,
    )


# ── incident ─────────────────────────────────────────────────────────────────


class Named(BaseModel):
    id: str
    name: str


class Cause(Named):
    said: str
    confidence: float


class Before(Named):
    what: str
    at: datetime


class Reaches(BaseModel):
    dependents: list[str]
    applications: list[str]


class IncidentSaid(Citing):
    id: str
    name: str
    severity: str | None
    state: str | None
    opened_at: datetime | None
    resolved_at: str | None
    minutes: int | None
    affected: list[Named]
    causes: list[Cause]
    changed_before: list[Before]
    reaches: Reaches


async def incident(asked: OneAsked, call: Call) -> IncidentSaid:
    reading = Reading()
    repository, entity = await _entity(call, asked.id)
    if entity.type is not EntityType.INCIDENT:
        raise UnknownThingError("LEKA knows no such incident.")
    detail = await KnowledgeService(repository).incident(entity)
    named = [
        *(t.entity for t in detail.affected),
        *(t.entity for t in detail.suspected_causes),
        *(e.entity for e in detail.changed_before),
    ]
    entities = await repository.by_ids([entity.id, *(b.id for b in named)])
    sources = await _sources_of(call.session, call.workspace_id, entities.values())
    return IncidentSaid(
        id=reading.entity(entity, sources, at=detail.opened_at),
        name=detail.name,
        severity=detail.severity or detail.priority,
        state=detail.state,
        opened_at=detail.opened_at,
        resolved_at=detail.resolved_at,
        minutes=detail.duration_minutes,
        affected=[
            Named(id=reading.entity(t.entity, sources), name=t.entity.name)
            for t in detail.affected[:MOST]
        ],
        causes=[
            Cause(
                id=reading.entity(t.entity, sources),
                name=t.entity.name,
                said=t.origin,
                confidence=round(t.confidence, 2),
            )
            for t in detail.suspected_causes[:MOST]
        ],
        changed_before=[
            Before(
                id=reading.entity(e.entity, sources, detail=e.kind, at=e.at),
                what=e.kind,
                name=e.entity.name,
                at=e.at,
            )
            for e in detail.changed_before[:MOST]
        ],
        reaches=Reaches(
            dependents=[t.name for t in detail.impact.dependents[:10]],
            applications=[t.name for t in detail.impact.applications[:10]],
        ),
        cited=reading.cited,
    )


# ── learned ──────────────────────────────────────────────────────────────────


class LearnedAsked(Period):
    types: list[str] = Field(default_factory=list, max_length=20, description=TYPES)


class Change(Thing):
    change: str = Field(description="appeared, changed, went, came_back.")
    fields: list[str]
    at: datetime


class LearnedSaid(Citing):
    since: datetime
    until: datetime
    things: list[Change]


async def learned(asked: LearnedAsked, call: Call) -> LearnedSaid:
    reading = Reading()
    since, until = _period(asked.since, asked.until, call.now)
    repository = EvolutionRepository(call.session, call.workspace_id)
    found = await learned_between(
        repository,
        set(),
        since=since,
        until=until,
        types=frozenset(_kinds(asked.types)),
        most=MOST,
    )
    entities = await repository.by_ids([item.thing.id for item in found])
    sources = await _sources_of(call.session, call.workspace_id, entities.values())
    return LearnedSaid(
        since=since,
        until=until,
        things=[
            Change(
                id=reading.entity(item.thing, sources, detail=item.change, at=item.at),
                name=item.thing.name,
                type=_type(item.thing),
                change=item.change,
                fields=list(item.fields),
                at=item.at,
            )
            for item in found
        ],
        cited=reading.cited,
    )


# ── sources ──────────────────────────────────────────────────────────────────


class Nothing(BaseModel):
    """What a read that takes nothing takes."""


class Watched(BaseModel):
    id: str
    kind: str
    name: str
    state: str
    health: str | None
    last_read: datetime | None


class SourcesSaid(Citing):
    sources: list[Watched]


async def sources(asked: Nothing, call: Call) -> SourcesSaid:
    reading = Reading()
    rows = (
        await call.session.execute(
            select(Source).where(Source.workspace_id == call.workspace_id).order_by(Source.name)
        )
    ).scalars()
    said: list[Watched] = []
    for source in rows:
        ident = reading.keep(
            Cited(
                id=f"source:{source.id}",
                kind="record",
                label=source.name,
                ref_type="source",
                ref_id=source.id,
                sources=[CitedSource(id=source.id, kind=source.kind.value, name=source.name)],
                detail=source.status.value,
                at=source.last_synced_at,
            )
        )
        said.append(
            Watched(
                id=ident,
                kind=source.kind.value,
                name=source.name,
                state=source.status.value,
                health=source.health_status.value if source.health_status else None,
                last_read=source.last_synced_at,
            )
        )
    return SourcesSaid(sources=said, cited=reading.cited)


# ── insights ─────────────────────────────────────────────────────────────────


class InsightsAsked(BaseModel):
    about: str | None = Field(default=None, max_length=100, description=f"Only about {AN_ID}")


class Open(BaseModel):
    id: str
    about: str
    category: str
    severity: str
    says: str | None
    since: datetime


class InsightsSaid(Citing):
    open: list[Open]


async def insights(asked: InsightsAsked, call: Call) -> InsightsSaid:
    reading = Reading()
    about = id_of(asked.about) if asked.about else None
    repository = IntelligenceRepository(call.session, call.workspace_id)
    found = await repository.about([about], limit=MOST) if about else await repository.top(MOST)
    said: list[Open] = []
    for finding in found:
        if finding.status != "open":
            continue
        ident = reading.keep(
            Cited(
                id=f"finding:{finding.id}",
                kind="inference",
                label=cut(finding.statement, 200) or finding.code,
                ref_type="finding",
                ref_id=finding.id,
                origin="leka",
                detail=f"{finding.category} · {finding.severity}",
                at=finding.first_seen_at,
                params={"code": finding.code, "params": dict(finding.params or {})},
            )
        )
        said.append(
            Open(
                id=ident,
                about=finding.subject_name,
                category=finding.category,
                severity=finding.severity,
                says=cut(finding.statement),
                since=finding.first_seen_at,
            )
        )
    return InsightsSaid(open=said, cited=reading.cited)


# ── overview ─────────────────────────────────────────────────────────────────


class OverviewSaid(BaseModel):
    things: dict[str, int]
    environments: list[str]
    built_at: datetime | None


async def overview(asked: Nothing, call: Call) -> OverviewSaid:
    rows = await call.session.execute(
        select(Entity.type, func.count())
        .where(Entity.workspace_id == call.workspace_id, Entity.lifecycle != Lifecycle.REMOVED)
        .group_by(Entity.type)
    )
    graph = GraphService(GraphRepository(call.session, call.workspace_id))
    return OverviewSaid(
        things={kind.value: count for kind, count in rows.tuples().all()},
        environments=await graph.environments(),
        built_at=await graph.built_at(),
    )


# ── registered ───────────────────────────────────────────────────────────────

VERSION = "1.0.0"
SKILLS = (
    Skill(
        key="find",
        version=VERSION,
        title="Find",
        summary="Find things LEKA knows by name or words: services, applications, repositories, "
        "databases, resources, teams, people, documents.",
        category="knowledge",
        input=FindAsked,
        output=FindSaid,
        run=find,
    ),
    Skill(
        key="describe",
        version=VERSION,
        title="Describe",
        summary="One thing: what it is, its state, what its sources say, its owners, what it is "
        "tied to.",
        category="knowledge",
        input=OneAsked,
        output=Described,
        run=describe,
    ),
    Skill(
        key="dependencies",
        version=VERSION,
        title="Dependencies",
        summary="What a thing depends on (downstream) or what depends on it (upstream), two "
        "steps at most.",
        category="architecture",
        input=DependenciesAsked,
        output=DependenciesSaid,
        run=dependencies,
        limitations=("Two steps at most; 25 things.",),
    ),
    Skill(
        key="happened",
        version=VERSION,
        title="What happened",
        summary="What happened in a period — deployments, merged pull requests, releases, "
        "change requests, incidents opened or resolved — everywhere, in one environment, or "
        "around one thing. The latest first.",
        category="operations",
        input=HappenedAsked,
        output=HappenedSaid,
        run=happened,
        limitations=("What the connected sources record: no source, no event.",),
    ),
    Skill(
        key="incident",
        version=VERSION,
        title="Incident",
        summary="One incident in detail: its severity and state, what it affected, what is said "
        "or suspected to have caused it, what changed in the 72 hours before.",
        category="operations",
        input=OneAsked,
        output=IncidentSaid,
        run=incident,
        limitations=("A suspected cause is inferred from what changed before: not proven.",),
    ),
    Skill(
        key="learned",
        version=VERSION,
        title="What LEKA learned",
        summary="What LEKA's model gained, changed or lost in a period: things that appeared in "
        "the sources, changed, went, came back.",
        category="knowledge",
        input=LearnedAsked,
        output=LearnedSaid,
        run=learned,
    ),
    Skill(
        key="sources",
        version=VERSION,
        title="Sources",
        summary="The sources LEKA reads — their kind, their state, when each was last read.",
        category="knowledge",
        input=Nothing,
        output=SourcesSaid,
        run=sources,
        permission=Permission.SOURCE_READ.value,
    ),
    Skill(
        key="insights",
        version=VERSION,
        title="Insights",
        summary="What LEKA already concluded and is still open — risks, gaps, conflicts — "
        "everywhere, or about one thing.",
        category="knowledge",
        input=InsightsAsked,
        output=InsightsSaid,
        run=insights,
    ),
    Skill(
        key="overview",
        version=VERSION,
        title="Overview",
        summary="What LEKA's model holds: how many things of each kind, the environments it "
        "knows, when it was last built.",
        category="knowledge",
        input=Nothing,
        output=OverviewSaid,
        run=overview,
    ),
)
READS = tuple(skill.key for skill in SKILLS)

register(*SKILLS)
