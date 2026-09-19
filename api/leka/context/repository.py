"""Database access for the context module.

The only place in this module where a query is written (architecture rule 4).
Retrieval — vector search, full-text, recency — lives here. Ranking does not:
that is a decision, and decisions belong in service.py.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class ContextRepository:
    """Retrieves candidate evidence for a workspace."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
