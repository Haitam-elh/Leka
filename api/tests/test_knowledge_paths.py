"""The shortest ways between two things (LEKA-369): GraphService.paths on a
graph held in memory — the repository's three reads stood in for —
test_knowledge_graph.py asks PostgreSQL through the API.

What these protect: the two searches meet in the middle and find every
shortest way, whichever end is the busier; five at most, the surest first;
none past the depth asked; a loop never makes a way longer or walks back on
itself; the smaller frontier is the one that steps.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import cast

from leka.knowledge import EntityType, GraphRepository, GraphService, RelationshipType
from leka.knowledge.graph import MAX_DEPTH, MAX_PATHS
from leka.knowledge.models import Entity, Lifecycle, Relationship


class Graph:
    """The three reads paths() makes, over entities and relationships held
    in memory."""

    def __init__(self, names: Sequence[str], ties: Sequence[tuple[str, str, float]]) -> None:
        self.ids = {name: uuid.uuid4() for name in names}
        self.entities = {
            one: Entity(
                id=one,
                type=EntityType.SERVICE,
                key=f"service:{name}",
                name=name,
                lifecycle=Lifecycle.ACTIVE,
            )
            for name, one in self.ids.items()
        }
        self.edges = {
            (edge := uuid.uuid4()): Relationship(
                id=edge,
                from_entity_id=self.ids[a],
                to_entity_id=self.ids[b],
                type=RelationshipType.DEPENDS_ON,
                confidence=sure,
                origin="stated",
                rule="stated",
                cross_source=False,
                attributes={},
            )
            for a, b, sure in ties
        }
        self.frontiers: list[int] = []

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Entity]:
        return {one: self.entities[one] for one in ids if one in self.entities}

    async def ties(
        self, frontier: Sequence[uuid.UUID], **_: object
    ) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, float]]:
        self.frontiers.append(len(frontier))
        near = set(frontier)
        return [
            (one, e.from_entity_id, e.to_entity_id, e.confidence)
            for one, e in self.edges.items()
            if e.from_entity_id in near or e.to_entity_id in near
        ]

    async def edges_by_ids(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Relationship]:
        return {one: self.edges[one] for one in ids}


async def _ways(
    graph: Graph, start: str, end: str, max_depth: int = MAX_DEPTH
) -> tuple[int | None, list[str]]:
    # The repository stood in for.
    service = GraphService(cast(GraphRepository, graph))
    found = await service.paths(graph.ids[start], graph.ids[end], max_depth=max_depth)
    assert found is not None
    return found.length, ["-".join(e.name for e in way.entities) for way in found.paths]


async def test_every_shortest_way_the_surest_first() -> None:
    graph = Graph(
        "abcde",
        [("a", "b", 0.9), ("b", "d", 0.9), ("a", "c", 0.5), ("c", "d", 1.0), ("d", "e", 1.0)],
    )

    assert await _ways(graph, "a", "d") == (2, ["a-b-d", "a-c-d"])
    assert await _ways(graph, "a", "e") == (3, ["a-b-d-e", "a-c-d-e"])
    # Read either way: the relationships' direction is not the walk's.
    assert await _ways(graph, "e", "a") == (3, ["e-d-b-a", "e-d-c-a"])


async def test_none_past_the_depth_asked() -> None:
    graph = Graph("abcde", [("a", "b", 1), ("b", "c", 1), ("c", "d", 1), ("d", "e", 1)])

    assert await _ways(graph, "a", "e") == (4, ["a-b-c-d-e"])
    assert await _ways(graph, "a", "e", max_depth=3) == (None, [])
    assert await _ways(graph, "a", "a") == (0, ["a"])


async def test_five_at_most_the_surest() -> None:
    middles = [f"m{n}" for n in range(9)]
    graph = Graph(
        ["a", "z", *middles],
        [
            *(("a", m, 0.1 * (n + 1)) for n, m in enumerate(middles)),
            *((m, "z", 1.0) for m in middles),
        ],
    )

    length, ways = await _ways(graph, "a", "z")

    assert length == 2
    assert len(ways) == MAX_PATHS
    assert ways == [f"a-m{n}-z" for n in (8, 7, 6, 5, 4)]


async def test_a_loop_never_lengthens_a_way() -> None:
    graph = Graph(
        "abcd",
        [("a", "b", 1), ("b", "c", 1), ("c", "a", 1), ("c", "d", 1), ("d", "b", 1)],
    )

    length, ways = await _ways(graph, "a", "d")

    assert (length, sorted(ways)) == (2, ["a-b-d", "a-c-d"])


async def test_the_smaller_frontier_steps() -> None:
    # A hub: a hundred things around the start, one way to the end.
    spokes = [f"s{n}" for n in range(100)]
    graph = Graph(
        ["hub", "x", "y", "end", *spokes],
        [
            *(("hub", s, 1.0) for s in spokes),
            ("hub", "x", 1.0),
            ("x", "y", 1.0),
            ("y", "end", 1.0),
        ],
    )

    assert await _ways(graph, "hub", "end") == (3, ["hub-x-y-end"])
    # The hub stepped once; then the end's side, not the hub's hundred.
    assert graph.frontiers == [1, 1, 1]
