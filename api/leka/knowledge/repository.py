"""Database access for the knowledge module.

The only place in this module where a query is written (architecture rule 4),
and the only place a graph traversal is expressed.

Every method takes workspace_id as its first argument. Not a convention —
rule 2 and rule 3 mean there is no legitimate query here that is not scoped
to one tenant.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class EntityRepository:
    """Reads and writes rows in `entities`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # upsert(workspace_id, candidates) -> Sequence[Entity]
    #     ON CONFLICT (workspace_id, source_id, external_id) DO UPDATE.
    #     The background loop runs continuously; a re-sync must update,
    #     never duplicate.
    # get(workspace_id, entity_id) -> Entity | None
    # search(workspace_id, type, query) -> Sequence[Entity]


class RelationshipRepository:
    """Reads and writes rows in `relationships`, and walks them."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # neighbours(workspace_id, entity_id, direction, depth) -> Neighbourhood
    #     Recursive CTE. Both traversal directions are indexed; keep an eye
    #     on depth, see docs/adr/001-postgresql.md.
