"""The files a run's intention was asked with, as its agent is given them
(2026-10-28): read by the module that keeps them — leka.intentions, above
this one — through the reader it registers here, as it registers its steps.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

Reader = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[list[dict[str, object]]]]
_reader: Reader | None = None


def read_attached_with(reader: Reader) -> None:
    """How an intention's files are read: leka.intentions registers it."""
    global _reader
    _reader = reader


async def attached_to(
    session: AsyncSession, workspace_id: uuid.UUID, intention_id: uuid.UUID | None
) -> list[dict[str, object]]:
    """What the files of a run's intention say — nothing for a run asked
    alone, or where no reader was registered."""
    if intention_id is None or _reader is None:
        return []
    return await _reader(session, workspace_id, intention_id)


__all__ = ["Reader", "attached_to", "read_attached_with"]
