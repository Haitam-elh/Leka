"""What an agent may read while it runs (LEKA-395): the company model, the
workspace's own, through tools — each read-only, each needing a permission
the person who asked holds, each reading only things of the types the agent
is about (runtime.in_scope).

    search_entities   things of the company model, by words
    read_entity       one thing, and what it is tied to
    dependencies      what one thing depends on, or what depends on it
                      (LEKA-400)
    what_happened     what happened around one thing in a period — an
                      incident, a deployment, a change, a release, a merge
                      (LEKA-400)
    read_content      what one thing's records say — a page's text, a
                      ticket's description, a README — the latest first
                      (2026-10-14: the architect drew without reading)

An agent is offered only the tools its front matter declares (`tools`),
when it declares any (LEKA-400): least privilege, said in its file.

A tool answers the model in JSON. What it may not read, it says so —
`out_of_scope`, `not_found` — and the run keeps it: a refusal is a step like
any other. It never says more than the model would see in Mon environnement.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from leka.capabilities.definition import Definition
from leka.capabilities.runtime import AgentTool, in_scope
from leka.knowledge import EntityType, GraphService, KnowledgeService

# Things a search gives back, at most.
MOST_HITS = 20
# Things around one, at most.
MOST_AROUND = 40
# How far dependencies are walked; how far back what happened is read.
MOST_DEPTH = 3
MOST_DAYS = 30
MOST_EVENTS = 40


@dataclass(frozen=True)
class Answer:
    """What a tool said, and how it went: ok, refused (out of scope, not
    found, said wrong), failed."""

    text: str
    outcome: str
    why: str | None = None


def _said(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _refused(why: str) -> Answer:
    return Answer(_said({"error": why}), "refused", why)


SEARCH = AgentTool(
    name="search_entities",
    description=(
        "Find things of the company model — applications, services, teams, "
        "people, documents… — by words. Only the types you may read."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The words to look for."},
            "types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only these types; every type you may read when none.",
            },
        },
        "required": ["query"],
    },
    permission="workspace:read",
)

READ = AgentTool(
    name="read_entity",
    description=(
        "Read one thing of the company model by its id: what it is, and what "
        "it is tied to — only things of the types you may read."
    ),
    parameters={
        "type": "object",
        "properties": {"id": {"type": "string", "description": "Its id, as given."}},
        "required": ["id"],
    },
    permission="workspace:read",
)

DEPENDENCIES = AgentTool(
    name="dependencies",
    description=(
        "What one thing depends on (depends_on), or what depends on it "
        "(used_by) — a few steps away — only things of the types you may read."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Its id, as given."},
            "direction": {"type": "string", "enum": ["depends_on", "used_by"]},
            "depth": {"type": "integer", "description": "Steps away, 1 to 3."},
        },
        "required": ["id", "direction"],
    },
    permission="workspace:read",
)

HAPPENED = AgentTool(
    name="what_happened",
    description=(
        "What happened around one thing over the last days — incidents opened "
        "or resolved, deployments, changes, releases, merges — the latest first, "
        "only things of the types you may read."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Its id, as given."},
            "days": {"type": "integer", "description": "How far back, 1 to 30."},
        },
        "required": ["id"],
    },
    permission="workspace:read",
)

CONTENT = AgentTool(
    name="read_content",
    description=(
        "What one thing's records say — a page's text, a ticket's description, a "
        "document's body, a repository's README — the latest first, each cut when long. "
        "Read it before you describe the thing: its name alone says little."
    ),
    parameters={
        "type": "object",
        "properties": {"id": {"type": "string", "description": "Its id, as given."}},
        "required": ["id"],
    },
    permission="workspace:read",
)

TOOLS: tuple[AgentTool, ...] = (SEARCH, READ, DEPENDENCIES, HAPPENED, CONTENT)
NAMES = frozenset(t.name for t in TOOLS)

Handler = Callable[[Mapping[str, Any]], Awaitable[Answer]]
# What a thing's records say (read_content): given by the runtime, which
# reads the ingestion's content — this module reads the model only.
Reader = Callable[[uuid.UUID], Awaitable[Sequence[Mapping[str, object]]]]


# What read_entity gives of a thing's attributes, at most: each list's
# first items, each text's start, the whole within MOST_ATTRIBUTES.
MOST_ITEMS = 60
MOST_TEXT = 500
MOST_ATTRIBUTES = 8_000


def attributes_of(attributes: Mapping[str, Any]) -> dict[str, object]:
    """A thing's attributes as the model is given them (2026-10-22: a
    table's columns, keys and indexes, a database's replicas, a service's
    tier — what an agent judges, not only its name): the empty left out,
    lists and texts cut, the whole bounded — what does not fit is named in
    `cut`."""
    kept: dict[str, object] = {}
    cut: list[str] = []
    size = 0
    for name, value in attributes.items():
        if value is None or value == [] or value == {} or value == "":
            continue
        if isinstance(value, list):
            value = [v[:MOST_TEXT] if isinstance(v, str) else v for v in value[:MOST_ITEMS]]
        elif isinstance(value, str):
            value = value[:MOST_TEXT]
        said = len(_said(value)) + len(name)
        if size + said > MOST_ATTRIBUTES:
            cut.append(name)
            continue
        kept[name] = value
        size += said
    if cut:
        kept["cut"] = cut
    return kept


def _types(definition: Definition, asked: object) -> list[EntityType] | None:
    """The types a search may look for: the agent's, narrowed to those
    asked — None when it asked only for types it may not read."""
    known = {t.value for t in EntityType}
    mine = [t for t in definition.entity_types if t in known]
    if isinstance(asked, list) and asked:
        wanted = [str(t) for t in asked]
        mine = [t for t in mine if t in wanted]
        if not mine:
            return None
    return [EntityType(t) for t in mine]


def _bounded(said: object, low: int, high: int, default: int) -> int:
    try:
        return min(max(int(str(said)), low), high)
    except ValueError:
        return default


def handlers(
    definition: Definition,
    graph: GraphService,
    knowledge: KnowledgeService | None = None,
    *,
    now: datetime | None = None,
    content: Reader | None = None,
) -> dict[str, Handler]:
    """Each tool, bound to the agent it serves and the workspace's model."""

    async def read_content(arguments: Mapping[str, Any]) -> Answer:
        try:
            wanted = uuid.UUID(str(arguments.get("id")))
        except ValueError:
            return _refused("not_an_id")
        brief = (await graph.briefs([wanted])).get(wanted)
        if brief is None:
            return _refused("not_found")
        if not in_scope(definition, brief.type.value):
            return _refused("out_of_scope")
        records = list(await content(wanted)) if content is not None else []
        return Answer(
            _said(
                {
                    "id": str(brief.id),
                    "type": brief.type.value,
                    "name": brief.name,
                    "records": records,
                }
            ),
            "ok",
        )

    async def search(arguments: Mapping[str, Any]) -> Answer:
        words = str(arguments.get("query") or "").strip()
        if not words:
            return _refused("query_missing")
        types = _types(definition, arguments.get("types"))
        if types is None:
            return _refused("out_of_scope")
        found = await graph.search(words, types=types, limit=MOST_HITS)
        return Answer(
            _said(
                {
                    "found": [
                        {
                            "id": str(hit.entity.id),
                            "type": hit.entity.type.value,
                            "name": hit.entity.name,
                            "key": hit.entity.key,
                            "lifecycle": hit.entity.lifecycle.value,
                            "sources": hit.sources,
                        }
                        for hit in found.entities
                    ]
                }
            ),
            "ok",
        )

    async def read(arguments: Mapping[str, Any]) -> Answer:
        try:
            wanted = uuid.UUID(str(arguments.get("id")))
        except ValueError:
            return _refused("not_an_id")
        brief = (await graph.briefs([wanted])).get(wanted)
        if brief is None:
            return _refused("not_found")
        if not in_scope(definition, brief.type.value):
            return _refused("out_of_scope")
        types = _types(definition, None) or []
        around = await graph.walk([wanted], depth=1, entity_types=types, limit=MOST_AROUND)
        held = await knowledge.attributes([wanted]) if knowledge is not None else {}
        nodes = {n.entity.id: n for n in around.nodes} if around else {}
        return Answer(
            _said(
                {
                    "id": str(brief.id),
                    "type": brief.type.value,
                    "name": brief.name,
                    "key": brief.key,
                    "lifecycle": brief.lifecycle.value,
                    "sources": nodes[wanted].sources if wanted in nodes else [],
                    "attributes": attributes_of(held.get(wanted, {})),
                    "tied_to": [
                        {
                            "relationship": r.type.value,
                            "from": str(r.from_entity_id),
                            "to": str(r.to_entity_id),
                            "confidence": r.confidence,
                            "origin": r.origin,
                        }
                        for r in (around.relationships if around else [])
                        if r.from_entity_id in nodes and r.to_entity_id in nodes
                    ],
                    "things": [
                        {"id": str(n.entity.id), "type": n.entity.type.value, "name": n.entity.name}
                        for n in nodes.values()
                        if n.entity.id != wanted
                    ],
                }
            ),
            "ok",
        )

    async def _scoped(arguments: Mapping[str, Any]) -> tuple[uuid.UUID, Answer | None]:
        try:
            wanted = uuid.UUID(str(arguments.get("id")))
        except ValueError:
            return uuid.UUID(int=0), _refused("not_an_id")
        brief = (await graph.briefs([wanted])).get(wanted)
        if brief is None:
            return wanted, _refused("not_found")
        if not in_scope(definition, brief.type.value):
            return wanted, _refused("out_of_scope")
        return wanted, None

    async def depends(arguments: Mapping[str, Any]) -> Answer:
        wanted, refused = await _scoped(arguments)
        if refused is not None:
            return refused
        direction = str(arguments.get("direction") or "")
        if direction not in ("depends_on", "used_by") or knowledge is None:
            return _refused("direction_unknown")
        # LEKA's words (knowledge): downstream, what it depends on; upstream,
        # what depends on it — what a failure of it reaches.
        found = await knowledge.dependencies(
            wanted,
            direction="downstream" if direction == "depends_on" else "upstream",
            depth=_bounded(arguments.get("depth"), 1, MOST_DEPTH, 1),
            environment=None,
        )
        if found is None:
            return _refused("not_found")
        kept = [n for n in found.nodes if in_scope(definition, n.entity.type.value)]
        return Answer(
            _said(
                {
                    "of": str(wanted),
                    "direction": direction,
                    "things": [
                        {
                            "id": str(n.entity.id),
                            "type": n.entity.type.value,
                            "name": n.entity.name,
                            "depth": n.depth,
                            "criticality": n.criticality,
                        }
                        for n in kept
                    ],
                    # What it reaches that the agent may not read: counted.
                    "left_out": len(found.nodes) - len(kept),
                    "truncated": found.truncated,
                }
            ),
            "ok",
        )

    async def happened(arguments: Mapping[str, Any]) -> Answer:
        wanted, refused = await _scoped(arguments)
        if refused is not None:
            return refused
        until = now or datetime.now(UTC)
        days = _bounded(arguments.get("days"), 1, MOST_DAYS, 7)
        events = await graph.events(
            [wanted], since=until - timedelta(days=days), until=until, limit=MOST_EVENTS
        )
        briefs = await graph.briefs(list({e for e, _, _, _ in events}))
        # Whether a deployment succeeded: « why do they fail? » is first
        # checked against it (2026-10-19).
        states = await graph.states(list(briefs))
        kept = [
            (briefs[e], at, kind)
            for e, at, kind, _ in events
            if e in briefs and in_scope(definition, briefs[e].type.value)
        ]
        return Answer(
            _said(
                {
                    "around": str(wanted),
                    "days": days,
                    "events": [
                        {
                            "id": str(b.id),
                            "type": b.type.value,
                            "name": b.name,
                            "what": kind,
                            "at": at.isoformat(),
                            **({"state": states[b.id]} if b.id in states else {}),
                        }
                        for b, at, kind in kept
                    ],
                    "left_out": len(events) - len(kept),
                }
            ),
            "ok",
        )

    return {
        SEARCH.name: search,
        READ.name: read,
        DEPENDENCIES.name: depends,
        HAPPENED.name: happened,
        CONTENT.name: read_content,
    }
