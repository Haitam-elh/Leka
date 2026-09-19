"""Database access for the connectors module.

The only place in this module where a query is written (architecture rule 4).
Every method takes a workspace_id and filters on it — there is no "fetch all
sources" here, because there is no context in which that is the right
question.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class SourceRepository:
    """Reads and writes rows in `sources`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # list_for_workspace(workspace_id) -> Sequence[Source]
    # get(workspace_id, source_id) -> Source | None
    # mark_synced(workspace_id, source_id, at) -> None
    # mark_failed(workspace_id, source_id, error) -> None
