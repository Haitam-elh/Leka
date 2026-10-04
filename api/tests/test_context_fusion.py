"""Context retrieval's pure parts (LEKA-371): a request's words, how what
retrievers find is combined, how a retriever fails alone, and how
relevance orders a context.

What these protect: the words that say something, folded, French and
English, a plural read as its word, and what each also means; a tsquery
for the records' text that keeps the words as written; a thing found high
by several retrievers ranking above a thing found by one, its relevance
scaled 0 to 1 and every way it was found kept; a retriever that errs or
times out undone alone, said, the others' findings kept; one with nothing
to start from skipped, and said; a context ordered by relevance after its
roots — or, none asked, after what the words found best — each found thing
saying whether it was reached or only found; the fingerprint moved by what
is held, not by a rank.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from leka.context.assembly import Relevance, assemble, fingerprint
from leka.context.language import content, expanded, words
from leka.context.retrieval import Ask, Found, Hit, Runner, anchors_of, fuse
from leka.context.schemas import ContextRequest, RetrievalMatch
from leka.knowledge import (
    ContextMaterial,
    EntityRead,
    EntityType,
    Lifecycle,
    MaterialEntity,
    MaterialRelationship,
    RelationshipRead,
    RelationshipType,
)

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
A, B, C, D = (uuid.uuid5(uuid.NAMESPACE_URL, name) for name in "abcd")


# ── the words ────────────────────────────────────────────────────────────────


def test_the_words_that_say_something_folded_in_either_language() -> None:
    assert words("Pourquoi la facturation est-elle si lente ?") == ["facturation", "lente"]
    assert words("Why is Billing API slow?") == ["billing", "api", "slow"]
    assert words("Où sont les données de l'équipe Paiements ?") == [
        "donnees",
        "equipe",
        "paiements",
    ]
    assert words("?!") == []
    assert words(None) == []


def test_what_each_word_also_means_its_plural_read_as_it() -> None:
    said = expanded(["facturation", "lente", "paiements"])
    assert said[:3] == ["facturation", "lente", "paiements"]
    assert {"billing", "invoice", "slow", "latency", "payment"} <= set(said)
    # A word no vocabulary knows is kept, alone.
    assert expanded(["checkout"]) == ["checkout"]


def test_the_records_text_is_searched_by_the_words_as_written_too() -> None:
    query = content("Procédure de reprise des données")
    assert query is not None
    terms = query.split(" | ")
    assert {"procédure:*", "données:*", "procedure:*", "donnees:*", "reprise:*"} <= set(terms)
    assert {"retry:*", "recovery:*"} <= set(terms)
    assert content("de la ?") is None


# ── combining what retrievers found ──────────────────────────────────────────


@dataclass(frozen=True)
class Fake:
    name: str
    weight: float = 1.0
    version: int = 1
    hits: tuple[uuid.UUID, ...] = ()
    error: Exception | None = None

    async def retrieve(self, ask: Ask) -> Found:
        if self.error is not None:
            raise self.error
        return Found(hits=[Hit(h, detail=f"{self.name} {i}") for i, h in enumerate(self.hits)])


def test_found_high_by_several_is_surer_than_found_by_one() -> None:
    search, graph = Fake("search", hits=(A, B, C)), Fake("graph", hits=(B, D))
    fused = fuse(
        [(search, Found([Hit(A), Hit(B), Hit(C)])), (graph, Found([Hit(B, "1", 1), Hit(D)]))]
    )

    order = sorted(fused, key=lambda i: -fused[i].score)
    assert order[0] == B
    assert fused[B].score > fused[A].score > fused[D].score > 0
    assert fused[C].score < fused[A].score
    assert all(0 < relevance.score <= 1 for relevance in fused.values())
    # Every way it was found, the surest first: first for the graph, second
    # for the search.
    assert [(m.retriever, m.rank) for m in fused[B].matches] == [("graph", 1), ("search", 2)]
    # Found first by every retriever that ran: as relevant as can be.
    alone = fuse([(search, Found([Hit(A)])), (graph, Found([Hit(A)]))])
    assert alone[A].score == 1.0
    assert anchors_of(fused, at_most=2) == order[:2]


# ── a retriever fails alone ──────────────────────────────────────────────────


class Savepoints:
    def __init__(self) -> None:
        self.opened: list[int] = []
        self.undone = 0

    @asynccontextmanager
    async def isolated(self, timeout_ms: int) -> AsyncIterator[None]:
        self.opened.append(timeout_ms)
        try:
            yield
        except Exception:
            self.undone += 1
            raise


def _ask() -> Ask:
    request = ContextRequest.model_validate(
        {
            "roots": [],
            "depth": 1,
            "relationships": [],
            "environment": None,
            "limit": 10,
            "strategy": "hybrid",
        }
    )
    return Ask(request=request, text="x", words=["x"], anchors=[], since=NOW, until=NOW)


async def test_a_retriever_that_fails_or_times_out_is_undone_alone_and_said() -> None:
    points = Savepoints()
    runner = Runner(points.isolated, timeout_ms=1234)

    await runner.run(Fake("search", hits=(A,)), _ask())
    await runner.run(Fake("content", error=RuntimeError("boom")), _ask())
    await runner.run(
        Fake("timeline", error=RuntimeError("canceling statement due to statement timeout")),
        _ask(),
    )
    await runner.run(Fake("paths"), _ask(), skip="Fewer than two roots.")

    assert points.opened == [1234, 1234, 1234]
    assert points.undone == 2
    assert [(r.retriever, r.status, r.found) for r in runner.reports()] == [
        ("search", "ok", 1),
        ("content", "failed", 0),
        ("timeline", "timeout", 0),
        ("paths", "skipped", 0),
    ]
    failed, timed_out, skipped = runner.reports()[1:]
    assert failed.error == "RuntimeError: the retriever failed."
    assert timed_out.error == "Took longer than 1234 ms."
    assert skipped.error == "Fewer than two roots."
    assert [retriever.name for retriever, _ in runner.ok()] == ["search"]


# ── relevance orders a context ───────────────────────────────────────────────


def _item(entity_id: uuid.UUID, name: str, depth: int | None) -> MaterialEntity:
    return MaterialEntity(
        entity=EntityRead(
            id=entity_id,
            type=EntityType.SERVICE,
            key=f"service:{name}",
            name=name,
            attributes={},
            lifecycle=Lifecycle.ACTIVE,
            version=1,
            schema_version=1,
            confidence=0.9,
            quality=None,
            first_seen_at=NOW,
            last_seen_at=NOW,
            removed_at=None,
        ),
        depth=depth,
        provenance={},
    )


def _tie(start: uuid.UUID, end: uuid.UUID) -> MaterialRelationship:
    return MaterialRelationship(
        relationship=RelationshipRead(
            id=uuid.uuid4(),
            from_entity_id=start,
            to_entity_id=end,
            type=RelationshipType.DEPENDS_ON,
            confidence=0.9,
            origin="stated",
            rule="stated",
            cross_source=False,
            attributes={},
        ),
        provenance=[],
        first_seen_at=NOW,
        changed_at=NOW,
    )


def _relevance(score: float, retriever: str, rank: int = 1) -> Relevance:
    return Relevance(
        score=score,
        matches=[RetrievalMatch(retriever=retriever, rank=rank, score=score, detail=None)],
    )


def test_the_most_relevant_first_after_what_the_words_found_best() -> None:
    # No root asked: A is what the words found best — the anchor. B is tied
    # to it; C and D are found, tied to nothing; D found higher than C.
    material = ContextMaterial(
        roots=[],
        entities=[_item(A, "a", 0), _item(B, "b", 1), _item(C, "c", None), _item(D, "d", None)],
        relationships=[_tie(A, B)],
        sources=[],
        truncated=False,
        built_at=NOW,
        model_version=9,
    )
    relevance = {
        A: _relevance(0.9, "search"),
        B: _relevance(0.2, "graph"),
        C: _relevance(0.3, "timeline"),
        D: _relevance(0.6, "content"),
    }
    made = assemble(material, limit=10, strategy="hybrid", relevance=relevance, anchors=[A])

    entities = [e for e in made.elements if e.kind == "entity"]
    assert [e.label for e in entities] == ["a", "d", "c", "b"]
    roles = {e.label: (e.reason.role, e.reason.depth, e.relevance) for e in entities}
    assert roles == {
        "a": ("found", 0, 0.9),
        "b": ("reached", 1, 0.2),
        "c": ("found", None, 0.3),
        "d": ("found", None, 0.6),
    }
    assert made.summary.by_retriever == {"content": 1, "graph": 1, "search": 1, "timeline": 1}

    # Ranks moved, nothing else did: the same context.
    moved = {**relevance, D: _relevance(0.6, "content", rank=4)}
    again = assemble(material, limit=10, strategy="hybrid", relevance=moved, anchors=[A])
    assert fingerprint(again.elements) == fingerprint(made.elements)


@pytest.mark.parametrize("asked", [[A], []])
def test_a_root_is_as_relevant_as_can_be(asked: list[uuid.UUID]) -> None:
    material = ContextMaterial(
        roots=asked,
        entities=[_item(A, "a", 0)],
        relationships=[],
        sources=[],
        truncated=False,
        built_at=NOW,
        model_version=9,
    )
    made = assemble(material, limit=10, strategy="hybrid", relevance={}, anchors=[A])
    assert made.elements[0].relevance == (1.0 if asked else 0.0)
    assert made.elements[0].reason.role == ("root" if asked else "found")
