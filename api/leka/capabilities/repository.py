"""Database access for the capabilities module.

The only place in this module where a query is written (architecture rule 4).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class CapabilityRunRepository:
    """Reads and writes the record of agent runs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
