"""Database access for the platform module.

The only place in this module where a query is written (architecture rule 4).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class WorkspaceRepository:
    """Reads and writes rows in `workspaces`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
