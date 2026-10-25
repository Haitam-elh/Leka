"""Dedicated agents (2026-10-25): an agent made for one organisation — its
architect, on its documentation — seen and run only by the organisations it
is assigned to, never sold.

    dedicated_to()   the agents assigned to a workspace
    assign()         one assigned, from now on — said by whom at LEKA
    unassign()       one no longer assigned

Assigned by LEKA from the server (python -m leka.ops.enterprise), never over
HTTP; read wherever an agent is shown or started: a refusal is the server's,
never only a screen's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.models import DedicatedAgent


async def dedicated_to(session: AsyncSession, workspace_id: uuid.UUID) -> frozenset[str]:
    """The agents assigned to this workspace."""
    found = await session.scalars(
        select(DedicatedAgent.key).where(DedicatedAgent.workspace_id == workspace_id)
    )
    return frozenset(found.all())


async def assign(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    key: str,
    *,
    by: str,
    now: datetime | None = None,
) -> bool:
    """`key` assigned to this workspace — True when it was not yet."""
    if key in await dedicated_to(session, workspace_id):
        return False
    session.add(
        DedicatedAgent(
            workspace_id=workspace_id,
            key=key,
            assigned_by=by[:100],
            assigned_at=now or datetime.now(UTC),
        )
    )
    await session.flush()
    return True


async def unassign(session: AsyncSession, workspace_id: uuid.UUID, key: str) -> bool:
    """`key` no longer assigned to this workspace — True when it was."""
    done = await session.execute(
        delete(DedicatedAgent).where(
            DedicatedAgent.workspace_id == workspace_id, DedicatedAgent.key == key
        )
    )
    return bool(getattr(done, "rowcount", 0))


__all__ = ["assign", "dedicated_to", "unassign"]
