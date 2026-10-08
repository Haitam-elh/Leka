"""What an agent may read while it runs (LEKA-395): the company model, the
workspace's own, through tools — each read-only, each needing a permission
the person who asked holds, each reading only things of the types the agent
is about (runtime.in_scope).

    search_entities   things of the company model, by words
    read_entity       one thing, and what it is tied to

A tool answers the model in JSON. What it may not read, it says so —
`out_of_scope`, `not_found` — and the run keeps it: a refusal is a step like
any other. It never says more than the model would see in Mon environnement.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from leka.capabilities.definition import Definition
from leka.capabilities.runtime import AgentTool, in_scope
from leka.knowledge import EntityType, GraphService

# Things a search gives back, at most.
MOST_HITS = 20
# Things around one, at most.
MOST_AROUND = 40


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

TOOLS: tuple[AgentTool, ...] = (SEARCH, READ)

Handler = Callable[[Mapping[str, Any]], Awaitable[Answer]]


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


def handlers(definition: Definition, graph: GraphService) -> dict[str, Handler]:
    """Each tool, bound to the agent it serves and the workspace's model."""

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

    return {SEARCH.name: search, READ.name: read}
