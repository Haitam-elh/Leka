"""How a context's material is gathered from the company model (LEKA-370).

A strategy reads the model — through leka.knowledge, never a customer's API
— and hands back what assembly orders, cuts to the budget and records.
Each has a name and a version, kept with every version of a context it
made: a strategy that gathers differently is a new version, and a context
says which one made it.

    neighbourhood   what surrounds the roots, `depth` steps away, through
                    the relationships asked, in one environment or all

The baseline. LEKA-371 adds the strategies an intention needs — by search,
by time around an incident, by paths between two things — beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from leka.context.schemas import ContextRequest
from leka.knowledge import ContextMaterial, GraphService, RelationshipType


class Strategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> int: ...

    async def gather(self, graph: GraphService, request: ContextRequest) -> ContextMaterial | None:
        """What the request asks for; None when a root is not in the model."""
        ...


@dataclass(frozen=True)
class Neighbourhood:
    """What surrounds the roots: a bounded walk, both ways, through the
    relationships asked — what a question about a thing needs first."""

    name: str = "neighbourhood"
    version: int = 1

    async def gather(self, graph: GraphService, request: ContextRequest) -> ContextMaterial | None:
        return await graph.material(
            request.roots,
            depth=request.depth,
            types=[RelationshipType(kind) for kind in request.relationships],
            environment=request.environment,
            limit=request.limit,
        )


STRATEGIES: dict[str, Strategy] = {"neighbourhood": Neighbourhood()}
