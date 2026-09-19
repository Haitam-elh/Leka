"""Database access for the intentions module.

The only place in this module where a query is written (architecture rule 4).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class IntentionRepository:
    """Reads and writes intentions and their approvals."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
