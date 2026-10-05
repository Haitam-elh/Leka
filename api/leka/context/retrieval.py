"""How a context's things are found (LEKA-371): retrievers, and how what
they find is combined.

    graph     around the roots — or what the words found best — through the
              relationships asked, `depth` steps: entities and relationships
    search    the request's words, and what they also mean, in the company
              model's own words: names, descriptions, labels, keys
    content   the same words in what the records say — a page's body, a
              ticket's description, a pull request's — read back to the
              things they are about
    timeline  what happened around them in a window of time: incidents
              opened and resolved, deployments, changes, releases, merges
    paths     the shortest ways between two roots, and what is on them

Each says what it found, best first, and on what — the words a thing
holds, how many steps away, the event and when. fuse() combines their
rankings, each weighed: a thing found high by several is surer than a
thing found high by one (reciprocal rank fusion) — and things a walk found
equally near share a rank. Its relevance is that sum, scaled from 0 to 1
by the most any thing could have had.

A RETRIEVER FAILS ALONE. Each runs in a savepoint with a statement
timeout (run()): one that errs or takes too long is undone, logged, and
said in the version's retrieval report — failed, timed out — and the
others' findings make the context. One with nothing to start from — no
words, no root to walk from — is skipped, and said so.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from typing import Protocol

import structlog

from leka.context.language import content, expanded
from leka.context.ranking import Relevance
from leka.context.schemas import ContextRequest, RetrievalMatch, RetrieverRunRead
from leka.ingestion import ContentRepository
from leka.knowledge import GraphService, RelationshipType

logger = structlog.get_logger(__name__)

# Reciprocal rank fusion: a thing at rank r adds weight / (K + r). K small:
# a retriever's first few matter, its twentieth little.
RRF_K = 10
# What a search finds, at most; a timeline's events; a way's length.
MAX_FOUND = 20
MAX_PATH_STEPS = 4
MAX_PAIRS = 6
# How long a retriever may take, in its savepoint, before it is stopped.
TIMEOUT_MS = 5_000


@dataclass(frozen=True)
class Hit:
    """A thing a retriever found, and on what."""

    entity_id: uuid.UUID
    detail: str | None = None
    depth: int | None = None


@dataclass(frozen=True)
class Found:
    """What a retriever found, best first, and what it was asked."""

    hits: list[Hit]
    detail: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class Ask:
    """What a retriever is asked."""

    request: ContextRequest
    text: str
    words: list[str]
    anchors: list[uuid.UUID]
    since: datetime
    until: datetime


class Retriever(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> int: ...

    @property
    def weight(self) -> float: ...

    async def retrieve(self, ask: Ask) -> Found: ...


@dataclass(frozen=True)
class Weighed:
    """A retriever whose findings a request weighs more, or less — an
    intention's kind (LEKA-373): what happened counts double when the
    question is what changed."""

    inner: Retriever
    factor: float

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def version(self) -> int:
        return self.inner.version

    @property
    def weight(self) -> float:
        return self.inner.weight * self.factor

    async def retrieve(self, ask: Ask) -> Found:
        return await self.inner.retrieve(ask)


@dataclass(frozen=True)
class Graph:
    """Around the anchors, through the relationships asked."""

    graph: GraphService
    name: str = "graph"
    version: int = 1
    weight: float = 1.0

    async def retrieve(self, ask: Ask) -> Found:
        request = ask.request
        walked = await self.graph.walk(
            ask.anchors,
            depth=request.depth,
            types=[RelationshipType(kind) for kind in request.relationships],
            environment=request.environment,
            limit=request.limit,
        )
        if walked is None:
            return Found(hits=[])
        nodes = sorted(
            (node for node in walked.nodes if node.depth > 0),
            key=lambda node: (node.depth, node.entity.name.casefold(), str(node.entity.id)),
        )
        return Found(
            hits=[Hit(node.entity.id, str(node.depth), node.depth) for node in nodes],
            detail=f"depth {request.depth}",
            truncated=walked.truncated,
        )


@dataclass(frozen=True)
class Search:
    """The request's words, and what they also mean, in the model's words."""

    graph: GraphService
    name: str = "search"
    version: int = 1
    weight: float = 1.0

    async def retrieve(self, ask: Ask) -> Found:
        searched = expanded(ask.words)
        found = await self.graph.matching(searched, limit=MAX_FOUND)
        return Found(
            hits=[Hit(entity_id, ", ".join(held) or None) for entity_id, _, held in found],
            detail=", ".join(searched),
        )


@dataclass(frozen=True)
class Content:
    """The same words in what the records themselves say."""

    records: ContentRepository
    name: str = "content"
    version: int = 1
    weight: float = 0.8

    async def retrieve(self, ask: Ask) -> Found:
        tsquery = content(ask.text)
        if tsquery is None:
            return Found(hits=[])
        found = await self.records.matching(tsquery, limit=MAX_FOUND)
        return Found(
            hits=[Hit(entity_id) for entity_id, _ in found],
            detail=", ".join(expanded(ask.words)),
        )


@dataclass(frozen=True)
class Timeline:
    """What happened around the anchors, in the window, the latest first."""

    graph: GraphService
    name: str = "timeline"
    version: int = 1
    weight: float = 0.8

    async def retrieve(self, ask: Ask) -> Found:
        events = await self.graph.events(ask.anchors, since=ask.since, until=ask.until)
        hits: dict[uuid.UUID, Hit] = {}
        for entity_id, at, kind, _ in events:
            hits.setdefault(entity_id, Hit(entity_id, f"{kind} {at.isoformat()}"))
        return Found(
            hits=list(hits.values()),
            detail=f"{ask.since.isoformat()}/{ask.until.isoformat()}",
        )


@dataclass(frozen=True)
class Paths:
    """What is on the shortest ways between two roots."""

    graph: GraphService
    name: str = "paths"
    version: int = 1
    weight: float = 1.2

    async def retrieve(self, ask: Ask) -> Found:
        hits: dict[uuid.UUID, Hit] = {}
        truncated = False
        pairs = list(combinations(ask.request.roots, 2))[:MAX_PAIRS]
        for start, end in pairs:
            ways = await self.graph.paths(start, end, max_depth=MAX_PATH_STEPS)
            if ways is None:
                continue
            truncated = truncated or ways.truncated
            for way in ways.paths:
                for entity in way.entities[1:-1]:
                    hits.setdefault(entity.id, Hit(entity.id, f"{len(way.relationships)} steps"))
        return Found(hits=list(hits.values()), detail=f"{len(pairs)} pairs", truncated=truncated)


def fuse(found: Sequence[tuple[Retriever, Found]]) -> dict[uuid.UUID, Relevance]:
    """What every retriever found, combined: each thing's relevance — the
    sum of weight / (RRF_K + rank) over the retrievers that found it,
    scaled by the most any thing could have had — and each way it was
    found, the surest first."""
    best = sum(retriever.weight / (RRF_K + 1) for retriever, _ in found) or 1.0
    scores: dict[uuid.UUID, float] = {}
    matches: dict[uuid.UUID, list[RetrievalMatch]] = {}
    for retriever, result in found:
        near = [hit.depth for hit in result.hits if hit.depth is not None]
        for position, hit in enumerate(result.hits, start=1):
            # Equally near is equally ranked (LEKA-372): a walk's things one
            # step away are all first, not first to tenth by name.
            rank = position if hit.depth is None else 1 + sum(1 for d in near if d < hit.depth)
            added = retriever.weight / (RRF_K + rank)
            scores[hit.entity_id] = scores.get(hit.entity_id, 0.0) + added
            matches.setdefault(hit.entity_id, []).append(
                RetrievalMatch(
                    retriever=retriever.name, rank=rank, score=round(added, 4), detail=hit.detail
                )
            )
    return {
        entity_id: Relevance(
            score=round(min(1.0, score / best), 4),
            matches=sorted(matches[entity_id], key=lambda m: (-m.score, m.retriever)),
        )
        for entity_id, score in scores.items()
    }


@dataclass(frozen=True)
class Run:
    """A retriever's run: what it found, or nothing, and its report."""

    retriever: Retriever
    found: Found | None
    report: RetrieverRunRead


@dataclass
class Runner:
    """Runs retrievers each alone: a savepoint, a timeout, its report."""

    isolated: Callable[[int], AbstractAsyncContextManager[None]]
    timeout_ms: int | None = None
    runs: list[Run] = field(default_factory=list)

    async def run(self, retriever: Retriever, ask: Ask, *, skip: str | None = None) -> Run:
        if skip is not None:
            return self._kept(retriever, None, "skipped", 0, error=skip)
        start = time.perf_counter()
        timeout = self.timeout_ms or TIMEOUT_MS
        try:
            async with self.isolated(timeout):
                found = await retriever.retrieve(ask)
        except Exception as error:
            ms = round((time.perf_counter() - start) * 1000)
            timed_out = "statement timeout" in str(error)
            logger.warning(
                "context_retriever_failed",
                retriever=retriever.name,
                status="timeout" if timed_out else "failed",
                error=type(error).__name__,
                ms=ms,
            )
            said = (
                f"Took longer than {timeout} ms."
                if timed_out
                else f"{type(error).__name__}: the retriever failed."
            )
            return self._kept(retriever, None, "timeout" if timed_out else "failed", ms, said)
        ms = round((time.perf_counter() - start) * 1000)
        return self._kept(retriever, found, "ok", ms)

    def ok(self) -> list[tuple[Retriever, Found]]:
        return [(run.retriever, run.found) for run in self.runs if run.found is not None]

    def reports(self) -> list[RetrieverRunRead]:
        return [run.report for run in self.runs]

    def _kept(
        self,
        retriever: Retriever,
        found: Found | None,
        status: str,
        ms: int,
        error: str | None = None,
    ) -> Run:
        report = RetrieverRunRead.model_validate(
            {
                "retriever": retriever.name,
                "version": retriever.version,
                "status": status,
                "found": len(found.hits) if found else 0,
                "ms": ms,
                "detail": found.detail if found else None,
                "error": error,
                "weight": round(retriever.weight, 4),
            }
        )
        run = Run(retriever, found, report)
        self.runs.append(run)
        return run


def anchors_of(relevance: Mapping[uuid.UUID, Relevance], *, at_most: int) -> list[uuid.UUID]:
    """What the words found best: where the graph and the timeline start
    when no root was asked."""
    ranked = sorted(relevance, key=lambda entity_id: (-relevance[entity_id].score, str(entity_id)))
    return ranked[:at_most]
