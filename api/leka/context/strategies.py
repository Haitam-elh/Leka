"""How a context's material is gathered from the company model (LEKA-370,
LEKA-371).

A strategy reads the model — through leka.knowledge, and the records' own
text through leka.ingestion, never a customer's API — and hands back what
assembly orders, cuts to the budget and records: the material, how
relevant each thing was found, and what each retriever did. Each has a
name and a version, kept with every version of a context it made.

    neighbourhood  v1  what surrounds the roots, `depth` steps away, through
                       the relationships asked (LEKA-370) — the graph alone
    hybrid         v1  the retrievers combined (retrieval.py): the request's
                       words in the model and in the records' text, what
                       surrounds the roots — or, none asked, what the words
                       found best — what happened around them in a window,
                       what is on the ways between two roots; each thing as
                       relevant as how high, and by how many, it was found

The search and the content run first: when no root was asked, what they
found best is where the graph and the timeline start (ANCHORS). The
timeline reads around them and what the graph found one step from them
(NEAR): an incident has no deployment of its own, the service it affects
has. A
retriever that fails or times out is said and left out (retrieval.Runner);
a context is failed only when every retriever that ran failed.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Protocol

from leka.context.assembly import Relevance
from leka.context.language import words
from leka.context.retrieval import (
    Ask,
    Content,
    Graph,
    Paths,
    Retriever,
    Runner,
    Search,
    Timeline,
    anchors_of,
    fuse,
)
from leka.context.schemas import ContextRequest, RetrieverRunRead
from leka.ingestion import ContentRepository
from leka.knowledge import ContextMaterial, GraphService, RelationshipType

# When no root is asked: where the graph and the timeline start — the best
# the words found.
ANCHORS = 3
# And what the timeline also reads around: what is one step from them.
NEAR = 10
EVERY_ONE_FAILED = "Every retriever failed: nothing could be read of the company model."


@dataclass(frozen=True)
class Tools:
    """What a strategy reads with: the graph, the records' text, a way to
    run a retriever alone, and the time it is."""

    graph: GraphService
    content: ContentRepository | None
    isolated: Callable[[int], AbstractAsyncContextManager[None]]
    now: datetime


@dataclass(frozen=True)
class Gathered:
    """What a strategy gathered: the material — none when every retriever
    failed, and why — how relevant each thing was found, where the walks
    started, and what each retriever did."""

    material: ContextMaterial | None
    relevance: dict[uuid.UUID, Relevance] | None
    anchors: list[uuid.UUID] = field(default_factory=list)
    retrieval: list[RetrieverRunRead] = field(default_factory=list)
    error: str | None = None


class Strategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> int: ...

    async def gather(self, tools: Tools, request: ContextRequest, purpose: str) -> Gathered | None:
        """What the request asks for; None when a root is not in the model."""
        ...


@dataclass(frozen=True)
class Neighbourhood:
    """What surrounds the roots: a bounded walk, both ways, through the
    relationships asked — what a question about a thing needs first."""

    name: str = "neighbourhood"
    version: int = 1

    async def gather(self, tools: Tools, request: ContextRequest, purpose: str) -> Gathered | None:
        material = await tools.graph.material(
            request.roots,
            depth=request.depth,
            types=[RelationshipType(kind) for kind in request.relationships],
            environment=request.environment,
            limit=request.limit,
        )
        if material is None:
            return None
        return Gathered(material=material, relevance=None, anchors=list(request.roots))


@dataclass(frozen=True)
class Hybrid:
    """The retrievers combined: by words, around the roots, in time, on the
    ways between them — the most relevant first."""

    name: str = "hybrid"
    version: int = 1

    def retrievers(self, tools: Tools) -> tuple[list[Retriever], list[Retriever]]:
        """What runs first — what finds the anchors — and what runs from
        them."""
        first: list[Retriever] = [Search(tools.graph)]
        if tools.content is not None:
            first.append(Content(tools.content))
        return first, [Graph(tools.graph), Timeline(tools.graph), Paths(tools.graph)]

    async def gather(self, tools: Tools, request: ContextRequest, purpose: str) -> Gathered | None:
        roots = list(dict.fromkeys(request.roots))
        if roots and await tools.graph.known(roots) != set(roots):
            return None
        text = request.query or purpose
        said = words(text)
        until = request.until or tools.now
        ask = Ask(
            request=request,
            text=text,
            words=said,
            anchors=roots,
            since=until - timedelta(days=request.window_days),
            until=until,
        )
        wanted = set(request.retrievers)
        runner = Runner(tools.isolated)
        first, then = self.retrievers(tools)
        for retriever in first:
            if wanted and retriever.name not in wanted:
                continue
            await runner.run(retriever, ask, skip=None if said else "No words to search.")
        anchors = roots or anchors_of(fuse(runner.ok()), at_most=ANCHORS)
        ask = replace(ask, anchors=anchors)
        for retriever in then:
            if wanted and retriever.name not in wanted:
                continue
            # What happened is read around the anchors and what is right
            # next to them: an incident has no deployment of its own, the
            # service it affects does.
            around = _around(anchors, runner) if retriever.name == "timeline" else anchors
            await runner.run(
                retriever,
                replace(ask, anchors=around),
                skip=_skip(retriever.name, roots, anchors),
            )
        reports = runner.reports()
        ran = [r for r in reports if r.status != "skipped"]
        if ran and all(r.status in {"failed", "timeout"} for r in ran):
            return Gathered(
                material=None,
                relevance=None,
                anchors=anchors,
                retrieval=reports,
                error=EVERY_ONE_FAILED,
            )
        found = runner.ok()
        relevance = fuse(found)
        depths: dict[uuid.UUID, int | None] = dict.fromkeys(anchors, 0)
        for retriever, result in found:
            if retriever.name == "graph":
                for hit in result.hits:
                    depths.setdefault(hit.entity_id, hit.depth)
        ranked = sorted(relevance, key=lambda i: (-relevance[i].score, str(i)))
        chosen = list(dict.fromkeys([*roots, *anchors, *ranked]))
        material = await tools.graph.gathered(
            {entity_id: depths.get(entity_id) for entity_id in chosen[: request.limit]},
            roots=roots,
            types=[RelationshipType(kind) for kind in request.relationships],
            environment=request.environment,
            truncated=len(chosen) > request.limit or any(r.truncated for _, r in found),
        )
        return Gathered(material=material, relevance=relevance, anchors=anchors, retrieval=reports)


def _around(anchors: list[uuid.UUID], runner: Runner) -> list[uuid.UUID]:
    """The anchors, and what the graph found one step from them."""
    near = [
        hit.entity_id
        for retriever, found in runner.ok()
        if retriever.name == "graph"
        for hit in found.hits
        if hit.depth == 1
    ]
    return list(dict.fromkeys([*anchors, *near[:NEAR]]))


def _skip(name: str, roots: list[uuid.UUID], anchors: list[uuid.UUID]) -> str | None:
    """Why a retriever that walks from something cannot."""
    if name == "paths" and len(roots) < 2:
        return "Fewer than two roots: no way between them to follow."
    if name in {"graph", "timeline"} and not anchors:
        return "Nothing to start from: no root, and the words found nothing."
    return None


STRATEGIES: dict[str, Strategy] = {"neighbourhood": Neighbourhood(), "hybrid": Hybrid()}
