"""LEKA's analyst: an intention answered by a language model that knows
what LEKA is, reads what the question needs through LEKA's own tools — to
read, never to act — and answers as a senior colleague would, every point
resting on something it read.

    the question as understood, what LEKA's rules found (analysis.py), the
    context assembled for it, the sources LEKA reads
            │
            ▼
    the model, told what LEKA is and how it knows what it knows, given:
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
            │  a few rounds at most; the last one must answer
            ▼
    its answer, checked: each point cites what a tool returned, what the
    rules found, or the context — a point citing nothing is dropped; an
    answer resting on nothing, when there was something to rest on, is not
    kept. What it cites becomes the analysis's evidence (Preuves).

Through the LLM runtime (LEKA-429): the workspace's model, routed, every
call kept, its cost said. Read only: a tool that would change anything
cannot be given to a model (RuntimeTool). The rules stay the analysis's
skeleton — its risk, its recommendations; the analyst is its intelligence.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import (
    ContextPack,
    Execution,
    LLMRuntime,
    Needs,
    RuntimeTool,
    Task,
    Tier,
)
from leka.connectors import Source
from leka.db import session_factory, workspace_scope
from leka.intelligence import IntelligenceRepository
from leka.intentions.analysis import Answer, Asked, Evidence, Point, Result, SourceRef
from leka.intentions.reads import HAPPENINGS, in_environment, learned_between
from leka.intentions.writing import Written, known_ids, material
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

# What the analyst asks of a model: tools, a structured answer, good analysis.
NEEDS = Needs(structured=True, tools=True, quality=2)
# Seconds for all of it; rounds of tools at most, the last one answering.
BUDGET = 120.0
ROUNDS = 6
# Room for its thinking and its answer: Gemini counts both.
MOST_TOKENS = 8000
# Where LEKA's customers are, until a workspace says its own zone.
TIMEZONE = "Europe/Paris"
# What one tool returns, at most.
MOST = 25
LONGEST = 300
# The context it is given to start from: the best of it, not all.
CONTEXT_CHARACTERS = 8000

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

PLATFORM = """You are LEKA's analyst. LEKA is a platform an IT department \
connects to its tools — GitHub or GitLab, its cloud (AWS, Azure, Google \
Cloud), its databases, its documentation (Confluence, Notion…), its ticketing \
and incident tools (Jira, PagerDuty…), its monitoring — and that reads them \
continuously to keep a living model of the company's systems:

- THINGS: services, applications, code repositories, databases, schemas and \
tables, infrastructure resources, cloud accounts, environments (production, \
staging…), teams, people, documents, business capabilities and processes.
- EVENTS: deployments, merged pull requests, releases, change requests, \
incidents — each dated, often tied to what it touched.
- RELATIONSHIPS: depends_on, part_of, deployed_to, runs_on, owns, \
maintains, documents, affects, caused_by…
- Every fact has its sources and a confidence: STATED by a source, or \
INFERRED by LEKA's rules. A state (up, down, degraded) is measured only when \
a monitoring tool is connected; otherwise it is read from a resource or \
deduced — say so, never present it as measured.

You answer a person of that company who asked LEKA a question. Work like a \
senior engineer who knows their systems:
1. Understand what is really asked, and over which period and environment.
2. Read what answers it with your tools — what changed, what happened, what \
depends on what, who owns what, what LEKA already concluded. Start from \
what you are given (what LEKA's rules already found, the context); fetch \
what is missing. A few precise calls, not every tool.
3. Cross-check: a deployment just before an incident on the same thing is a \
probable cause, not a proven one.
4. Answer.

How you answer:
- The answer first, in its first sentence, plainly — then the specifics: \
names, versions, counts, dates and hours in the asker's time zone \
(« hier à 15h57 »), who or what is involved, what followed.
- Facts and inferences apart: what a source states is a fact; what you \
conclude is said as likely, with why.
- When nothing is found, say exactly what you checked — which sources, \
which period, when they were last read — so « nothing changed » can be \
trusted; and what LEKA cannot see (no monitoring connected, a source in \
error, a source never read).
- Never invent: no name, date, figure, owner or cause that your tools, the \
rules or the context did not give you.
- No internal words: say « LEKA », never « entity », « context element », \
« company model », « finding id ».
- In the language of the question (French when asked in French), in the \
tone of a colleague: precise, brief, no filler. Two to six sentences of \
answer, then at most eight points.
- Each point cites the ids it rests on, exactly as given by your tools, the \
rules or the context (« event:… », « entity:… », « finding:… », \
« source:… », « context:… », or a rule's finding id). A point you cannot \
cite is not written.
- You never act on the company's systems and never tell anyone to run \
something in production: a person decides, through LEKA."""


# ── what it read ─────────────────────────────────────────────────────────────


class Reading:
    """What the analyst read, by the id it may cite: every thing, event,
    source or conclusion a tool returned — the evidence its answer rests on
    when it cites it."""

    def __init__(self) -> None:
        self.read: dict[str, Evidence] = {}

    def keep(self, evidence: Evidence) -> str:
        self.read.setdefault(evidence.id, evidence)
        return evidence.id

    def entity(
        self,
        thing: Entity | EntityBrief,
        sources: Mapping[uuid.UUID, tuple[SourceRef, ...]],
        *,
        detail: str | None = None,
        at: datetime | None = None,
    ) -> str:
        kind = thing.type.value if hasattr(thing.type, "value") else str(thing.type)
        happening = EntityType(kind) in HAPPENINGS
        return self.keep(
            Evidence(
                id=f"{'event' if happening else 'entity'}:{thing.id}",
                kind="event" if happening else "entity",
                label=thing.name,
                ref_type=kind,
                ref_id=thing.id,
                sources=sources.get(thing.id, ()),
                detail=_cut(detail),
                at=at,
            )
        )


def _cut(text: object, longest: int = LONGEST) -> str | None:
    if text is None:
        return None
    said = str(text)
    return said if len(said) <= longest else said[: longest - 1] + "…"


def _id_of(said: object) -> uuid.UUID | None:
    """The thing an id names — « entity:… », « event:… », or the uuid alone."""
    text = str(said or "").strip()
    if ":" in text:
        text = text.split(":", 1)[1]
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def _when(said: object, default: datetime) -> datetime:
    try:
        moment = datetime.fromisoformat(str(said))
    except ValueError:
        return default
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


KINDS = frozenset(kind.value for kind in EntityType)


def _types(arguments: Mapping[str, Any]) -> frozenset[EntityType]:
    """The kinds a model asked for, as LEKA names them — what it made up,
    left out."""
    asked = arguments.get("types") or []
    return frozenset(EntityType(t) for t in asked if isinstance(t, str) and t in KINDS)


def _type(entity: Entity | EntityBrief) -> str:
    return entity.type.value if hasattr(entity.type, "value") else str(entity.type)


def _said(attributes: Mapping[str, object]) -> dict[str, object]:
    """What a thing's attributes say worth telling, short."""
    told: dict[str, object] = {}
    for key in SAID:
        value = attributes.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            told[key] = [_cut(v, 80) for v in value[:8]]
        elif isinstance(value, (str, int, float, bool)):
            told[key] = _cut(value) if isinstance(value, str) else value
    return told


async def _sources_of(
    session: AsyncSession, workspace_id: uuid.UUID, entities: Iterable[Entity]
) -> dict[uuid.UUID, tuple[SourceRef, ...]]:
    """Each thing's sources, by its provenance."""
    rows = await session.execute(
        select(Source.id, Source.kind, Source.name).where(Source.workspace_id == workspace_id)
    )
    named = {ident: (kind.value, name) for ident, kind, name in rows.tuples().all()}
    found: dict[uuid.UUID, tuple[SourceRef, ...]] = {}
    for entity in entities:
        said = (entity.provenance or {}).get("sources") or []
        refs: dict[uuid.UUID, SourceRef] = {}
        for item in said if isinstance(said, list) else []:
            source = _id_of(item.get("source_id") if isinstance(item, dict) else None)
            if source is not None:
                kind, name = named.get(source, (None, None))
                refs[source] = SourceRef(source, kind, name)
        found[entity.id] = tuple(refs.values())
    return found


# ── its tools ────────────────────────────────────────────────────────────────


def _object(properties: Mapping[str, Any], required: Sequence[str] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": dict(properties), "required": list(required)}


PERIOD = {
    "since": {"type": "string", "description": "ISO 8601 date-time, the start."},
    "until": {"type": "string", "description": "ISO 8601 date-time, the end."},
}
ID = {"type": "string", "description": "An id as a tool gave it: « entity:… » or « event:… »."}


class Tools:
    """LEKA's own reads, as a model may call them — every one read only, in
    the workspace's scope, its answer short and citable."""

    def __init__(self, workspace_id: uuid.UUID, asked: Asked, now: datetime) -> None:
        self.workspace_id = workspace_id
        self.asked = asked
        self.now = now
        self.reading = Reading()

    # Each tool in its own session, in the workspace's scope.
    async def _in(self, read: Callable[[AsyncSession], Awaitable[object]]) -> str:
        with workspace_scope(self.workspace_id):
            async with session_factory() as session:
                said = await read(session)
        return json.dumps(said, ensure_ascii=False, default=str)

    def _period(self, arguments: Mapping[str, Any]) -> tuple[datetime, datetime]:
        since = _when(arguments.get("since"), self.asked.since or self.now - timedelta(days=7))
        until = _when(arguments.get("until"), self.asked.until or self.now)
        return min(since, until), max(since, until)

    def tools(self) -> list[RuntimeTool]:
        return [
            RuntimeTool(
                "find",
                "Find things LEKA knows by name or words: services, applications, repositories, "
                "databases, resources, teams, people, documents.",
                _object(
                    {
                        "query": {"type": "string"},
                        "types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Kinds to keep: service, application, repository, "
                            "database, infra_resource, team, person, document…",
                        },
                    },
                    ["query"],
                ),
                self.find,
            ),
            RuntimeTool(
                "describe",
                "One thing: what it is, its state, what its sources say, its owners, what it is "
                "tied to.",
                _object({"id": ID}, ["id"]),
                self.describe,
            ),
            RuntimeTool(
                "dependencies",
                "What a thing depends on (downstream) or what depends on it (upstream), two "
                "steps at most.",
                _object(
                    {
                        "id": ID,
                        "direction": {"type": "string", "enum": ["downstream", "upstream"]},
                    },
                    ["id", "direction"],
                ),
                self.dependencies,
            ),
            RuntimeTool(
                "happened",
                "What happened in a period — deployments, merged pull requests, releases, "
                "change requests, incidents opened or resolved — everywhere, in one "
                "environment, or around one thing. The latest first.",
                _object(
                    {
                        **PERIOD,
                        "environment": {"type": "string"},
                        "around": ID,
                    }
                ),
                self.happened,
            ),
            RuntimeTool(
                "incident",
                "One incident in detail: its severity and state, what it affected, what is "
                "said or suspected to have caused it, what changed in the 72 hours before.",
                _object({"id": ID}, ["id"]),
                self.incident,
            ),
            RuntimeTool(
                "learned",
                "What LEKA's model gained, changed or lost in a period: things that appeared "
                "in the sources, changed, went, came back.",
                _object(
                    {
                        **PERIOD,
                        "types": {"type": "array", "items": {"type": "string"}},
                    }
                ),
                self.learned,
            ),
            RuntimeTool(
                "sources",
                "The sources LEKA reads — their kind, their state, when each was last read.",
                _object({}),
                self.sources,
            ),
            RuntimeTool(
                "insights",
                "What LEKA already concluded and is still open — risks, gaps, conflicts — "
                "everywhere, or about one thing.",
                _object({"about": ID}),
                self.insights,
            ),
            RuntimeTool(
                "overview",
                "What LEKA's model holds: how many things of each kind, the environments it "
                "knows, when it was last built.",
                _object({}),
                self.overview,
            ),
        ]

    async def find(self, arguments: Mapping[str, Any]) -> str:
        typed = str(arguments.get("query") or "").strip()[:200]
        types = [
            EntityType(t)
            for t in arguments.get("types") or []
            if t in EntityType._value2member_map_
        ]

        async def read(session: AsyncSession) -> object:
            graph = GraphService(GraphRepository(session, self.workspace_id))
            found = await graph.search(typed, types=types, limit=MOST)
            briefs = [hit.entity for hit in found.entities]
            entities = await EntityRepository(session, self.workspace_id).by_ids(
                [b.id for b in briefs]
            )
            sources = await _sources_of(session, self.workspace_id, entities.values())
            return {
                "found": [
                    {
                        "id": self.reading.entity(hit.entity, sources),
                        "name": hit.entity.name,
                        "type": _type(hit.entity),
                        "lifecycle": hit.entity.lifecycle.value,
                        "in": hit.holder.name if hit.holder else None,
                    }
                    for hit in found.entities
                ]
            }

        return await self._in(read)

    async def describe(self, arguments: Mapping[str, Any]) -> str:
        ident = _id_of(arguments.get("id"))

        async def read(session: AsyncSession) -> object:
            repository = EntityRepository(session, self.workspace_id)
            entity = (await repository.by_ids([ident])).get(ident) if ident else None
            if entity is None:
                return {"error": "LEKA knows no such thing."}
            graph_repository = GraphRepository(session, self.workspace_id)
            # Who answers for it as LEKA reads it everywhere (LEKA-365):
            # owners, maintainers, leads, who knows it — said or inferred.
            held = await KnowledgeService(repository).responsibility(entity)
            edges = await graph_repository.around([entity.id], list(RelationshipType))
            others = await repository.by_ids(
                [
                    e.to_entity_id if e.from_entity_id == entity.id else e.from_entity_id
                    for e in edges
                ]
            )
            sources = await _sources_of(session, self.workspace_id, [entity, *others.values()])
            ties = []
            for edge in sorted(edges, key=lambda e: -e.confidence)[: MOST * 2]:
                outgoing = edge.from_entity_id == entity.id
                other = others.get(edge.to_entity_id if outgoing else edge.from_entity_id)
                if other is None or other.lifecycle is Lifecycle.REMOVED:
                    continue
                ties.append(
                    {
                        "relation": edge.type.value,
                        "direction": "to" if outgoing else "from",
                        "with": {
                            "id": self.reading.entity(other, sources),
                            "name": other.name,
                            "type": _type(other),
                        },
                        "said": edge.origin,
                    }
                )
            return {
                "id": self.reading.entity(entity, sources, at=entity.occurred_at),
                "name": entity.name,
                "type": _type(entity),
                "lifecycle": entity.lifecycle.value,
                "attributes": _said(entity.attributes or {}),
                "happened_at": entity.occurred_at,
                "responsibility": {
                    "owners": [
                        {"name": t.entity.name, "type": _type(t.entity), "said": t.origin}
                        for t in held.owners
                    ],
                    "leads": [lead.name for lead in held.leads],
                    "maintainers": [
                        {"name": t.entity.name, "said": t.origin} for t in held.maintainers
                    ],
                    "experts": [t.entity.name for t in held.experts[:5]],
                    "escalation": held.escalation_policy,
                },
                "ties": ties[: MOST * 2],
                "sources": [
                    {"id": f"source:{s.id}", "kind": s.kind, "name": s.name}
                    for s in sources.get(entity.id, ())
                ],
            }

        return await self._in(read)

    async def dependencies(self, arguments: Mapping[str, Any]) -> str:
        ident = _id_of(arguments.get("id"))
        direction: Literal["downstream", "upstream"] = (
            "upstream" if arguments.get("direction") == "upstream" else "downstream"
        )

        async def read(session: AsyncSession) -> object:
            if ident is None:
                return {"error": "No such thing."}
            knowledge = KnowledgeService(EntityRepository(session, self.workspace_id))
            found = await knowledge.dependencies(
                ident, direction=direction, depth=2, environment=self.asked.environment
            )
            if found is None:
                return {"error": "LEKA knows no such thing."}
            entities = await EntityRepository(session, self.workspace_id).by_ids(
                [n.entity.id for n in found.nodes[:MOST]]
            )
            sources = await _sources_of(session, self.workspace_id, entities.values())
            return {
                "of": found.root.name,
                "direction": direction,
                "things": [
                    {
                        "id": self.reading.entity(node.entity, sources),
                        "name": node.entity.name,
                        "type": _type(node.entity),
                        "steps": node.depth,
                        "criticality": node.criticality,
                    }
                    for node in found.nodes[:MOST]
                ],
                "more": found.truncated or len(found.nodes) > MOST,
            }

        return await self._in(read)

    async def happened(self, arguments: Mapping[str, Any]) -> str:
        since, until = self._period(arguments)
        around = _id_of(arguments.get("around"))
        environment = str(arguments.get("environment") or "") or None

        async def read(session: AsyncSession) -> object:
            repository = EntityRepository(session, self.workspace_id)
            knowledge = KnowledgeService(repository)
            entity = (await repository.by_ids([around])).get(around) if around else None
            timeline = await knowledge.timeline(
                entity, since=since, until=until, kinds=list(EVENTS), limit=MOST * 2
            )
            events = [e for e in timeline.events if in_environment(e.environment, environment)][
                : MOST * 2
            ]
            entities = await repository.by_ids([e.entity.id for e in events])
            sources = await _sources_of(session, self.workspace_id, entities.values())
            said = []
            for event in events:
                thing = entities.get(event.entity.id)
                said.append(
                    {
                        "id": self.reading.entity(
                            event.entity, sources, detail=event.kind, at=event.at
                        ),
                        "what": event.kind,
                        "name": event.entity.name,
                        "at": event.at,
                        "state": event.state,
                        "environment": event.environment,
                        "on": event.via.name if event.via else None,
                        "details": _said(thing.attributes or {}) if thing else {},
                    }
                )
            return {
                "since": since,
                "until": until,
                "around": entity.name if entity else None,
                "environment": environment,
                "events": said,
                "more": timeline.truncated,
            }

        return await self._in(read)

    async def incident(self, arguments: Mapping[str, Any]) -> str:
        ident = _id_of(arguments.get("id"))

        async def read(session: AsyncSession) -> object:
            repository = EntityRepository(session, self.workspace_id)
            entity = (await repository.by_ids([ident])).get(ident) if ident else None
            if entity is None or entity.type is not EntityType.INCIDENT:
                return {"error": "LEKA knows no such incident."}
            detail = await KnowledgeService(repository).incident(entity)
            named = [
                *(t.entity for t in detail.affected),
                *(t.entity for t in detail.suspected_causes),
                *(e.entity for e in detail.changed_before),
            ]
            entities = await repository.by_ids([entity.id, *(b.id for b in named)])
            sources = await _sources_of(session, self.workspace_id, entities.values())
            return {
                "id": self.reading.entity(entity, sources, at=detail.opened_at),
                "name": detail.name,
                "severity": detail.severity or detail.priority,
                "state": detail.state,
                "opened_at": detail.opened_at,
                "resolved_at": detail.resolved_at,
                "minutes": detail.duration_minutes,
                "affected": [
                    {"id": self.reading.entity(t.entity, sources), "name": t.entity.name}
                    for t in detail.affected[:MOST]
                ],
                "causes": [
                    {
                        "id": self.reading.entity(t.entity, sources),
                        "name": t.entity.name,
                        "said": t.origin,
                        "confidence": round(t.confidence, 2),
                    }
                    for t in detail.suspected_causes[:MOST]
                ],
                "changed_before": [
                    {
                        "id": self.reading.entity(e.entity, sources, detail=e.kind, at=e.at),
                        "what": e.kind,
                        "name": e.entity.name,
                        "at": e.at,
                    }
                    for e in detail.changed_before[:MOST]
                ],
                "reaches": {
                    "dependents": [t.name for t in detail.impact.dependents[:10]],
                    "applications": [t.name for t in detail.impact.applications[:10]],
                },
            }

        return await self._in(read)

    async def learned(self, arguments: Mapping[str, Any]) -> str:
        since, until = self._period(arguments)
        types = frozenset(
            EntityType(t)
            for t in arguments.get("types") or []
            if t in EntityType._value2member_map_
        )

        async def read(session: AsyncSession) -> object:
            repository = EvolutionRepository(session, self.workspace_id)
            found = await learned_between(
                repository, set(), since=since, until=until, types=types, most=MOST
            )
            entities = await repository.by_ids([item.thing.id for item in found])
            sources = await _sources_of(session, self.workspace_id, entities.values())
            return {
                "since": since,
                "until": until,
                "things": [
                    {
                        "id": self.reading.entity(
                            item.thing, sources, detail=item.change, at=item.at
                        ),
                        "name": item.thing.name,
                        "type": _type(item.thing),
                        "change": item.change,
                        "fields": list(item.fields),
                        "at": item.at,
                    }
                    for item in found
                ],
            }

        return await self._in(read)

    async def sources(self, arguments: Mapping[str, Any]) -> str:
        return await self._in(lambda session: self.watched(session))

    async def watched(self, session: AsyncSession) -> object:
        rows = (
            await session.execute(
                select(Source).where(Source.workspace_id == self.workspace_id).order_by(Source.name)
            )
        ).scalars()
        said = []
        for source in rows:
            ident = self.reading.keep(
                Evidence(
                    id=f"source:{source.id}",
                    kind="record",
                    label=source.name,
                    ref_type="source",
                    ref_id=source.id,
                    sources=(SourceRef(source.id, source.kind.value, source.name),),
                    detail=source.status.value,
                    at=source.last_synced_at,
                )
            )
            said.append(
                {
                    "id": ident,
                    "kind": source.kind.value,
                    "name": source.name,
                    "state": source.status.value,
                    "health": source.health_status.value if source.health_status else None,
                    "last_read": source.last_synced_at,
                }
            )
        return {"sources": said}

    async def insights(self, arguments: Mapping[str, Any]) -> str:
        about = _id_of(arguments.get("about"))

        async def read(session: AsyncSession) -> object:
            repository = IntelligenceRepository(session, self.workspace_id)
            found = (
                await repository.about([about], limit=MOST) if about else await repository.top(MOST)
            )
            said = []
            for finding in found:
                if finding.status != "open":
                    continue
                ident = self.reading.keep(
                    Evidence(
                        id=f"finding:{finding.id}",
                        kind="inference",
                        label=_cut(finding.statement, 200) or finding.code,
                        ref_type="finding",
                        ref_id=finding.id,
                        origin="leka",
                        detail=f"{finding.category} · {finding.severity}",
                        at=finding.first_seen_at,
                        params={"code": finding.code, "params": dict(finding.params or {})},
                    )
                )
                said.append(
                    {
                        "id": ident,
                        "about": finding.subject_name,
                        "category": finding.category,
                        "severity": finding.severity,
                        "says": _cut(finding.statement),
                        "since": finding.first_seen_at,
                    }
                )
            return {"open": said}

        return await self._in(read)

    async def overview(self, arguments: Mapping[str, Any]) -> str:
        async def read(session: AsyncSession) -> object:
            rows = await session.execute(
                select(Entity.type, func.count())
                .where(
                    Entity.workspace_id == self.workspace_id,
                    Entity.lifecycle != Lifecycle.REMOVED,
                )
                .group_by(Entity.type)
            )
            graph = GraphService(GraphRepository(session, self.workspace_id))
            return {
                "things": {kind.value: count for kind, count in rows.tuples().all()},
                "environments": await graph.environments(),
                "built_at": await graph.built_at(),
            }

        return await self._in(read)


# ── what it is given, what it gives back ─────────────────────────────────────


def given(asked: Asked, result: Result, now: datetime, watched: object) -> dict[str, Any]:
    """What the analyst starts from: what LEKA's rules found, in the shape
    the synthesis has always been given (writing.material) — and when it is,
    in which zone, what LEKA reads."""
    zone = ZoneInfo(TIMEZONE)
    said = material(asked, result)
    for end in ("since", "until"):
        moment = getattr(asked, end)
        said["period"][end] = (
            moment.astimezone(zone).isoformat(timespec="minutes") if moment else None
        )
    return {
        "now": now.astimezone(zone).isoformat(timespec="minutes"),
        "time_zone": TIMEZONE,
        **said,
        "understood": {"mode": asked.mode, "kind": asked.kind, "acting": asked.acting},
        "environment": asked.environment,
        "about": [{"id": f"entity:{s.id}", "name": s.name, "type": s.type} for s in asked.subjects],
        "summary": [n.text for n in result.summary],
        "sources": watched,
    }


def grounded(written: Written, known: frozenset[str]) -> tuple[tuple[Point, ...], frozenset[str]]:
    """The points that cite what it read or was given, and every id they
    cite."""
    points = tuple(
        Point(text=p.text.strip(), cites=cites)
        for p in written.points
        if p.text.strip() and (cites := tuple(dict.fromkeys(c for c in p.cites if c in known)))
    )
    return points, frozenset(c for p in points for c in p.cites)


async def answer(
    runtime: LLMRuntime,
    workspace_id: uuid.UUID,
    asked: Asked,
    result: Result,
    context: ContextPack,
    *,
    now: datetime,
) -> tuple[Execution, Answer | None, tuple[Evidence, ...]]:
    """The question answered by LEKA's analyst, through the runtime with
    LEKA's tools: its answer and the evidence it cites — none, said why,
    when no model gave one it could keep."""
    tools = Tools(workspace_id, asked, now)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            watched = await tools.watched(session)
    pack = ContextPack.of(context.items, ref=context.ref, characters=CONTEXT_CHARACTERS)

    def known() -> frozenset[str]:
        return known_ids(result, pack) | frozenset(tools.reading.read)

    def check(written: Any, _given: ContextPack) -> list[str]:
        if not isinstance(written, Written) or not written.answer.strip():
            return ["no answer"]
        points, _ = grounded(written, known())
        held = bool(result.findings or result.causes or tools.reading.read)
        return [] if points or not held else ["it cites nothing it read or was given"]

    done = await runtime.run(
        Task(
            purpose="capability.synthesis",
            instructions=PLATFORM,
            input=given(asked, result, now, watched),
            context=pack,
            output=Written,
            check=check,
            needs=NEEDS,
            tier=Tier.FAST,
            max_tokens=MOST_TOKENS,
            budget=BUDGET,
            tools=tools.tools(),
            rounds=ROUNDS,
            conclude=True,
            ref=f"intention:{asked.id}",
        )
    )
    if not done.ok:
        return done, None, ()
    written: Written = done.value
    points, cited = grounded(written, known())
    evidence = tuple(tools.reading.read[c] for c in cited if c in tools.reading.read)
    return (
        done,
        Answer(
            text=written.answer.strip(),
            points=points,
            caveats=tuple(c.strip() for c in written.caveats if c.strip()),
            provider=done.provider or "",
            model=done.model or "",
            version=done.version or "",
        ),
        evidence,
    )
