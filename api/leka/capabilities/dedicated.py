"""Dedicated agents (2026-10-25): an agent made for one organisation — its
architect, on its documentation — seen and run only by the organisations it
is assigned to, never sold.

    dedicated_to()   the agents assigned to a workspace
    hidden_from()    those it may not see: dedicated to others
    assign()         one assigned, from now on — said by whom at LEKA
    unassign()       one no longer assigned
    instructions_of() its organisation's own instructions, if it has them
    instruct()       those instructions given, or taken back (None)
    own_definition() the agent as it runs here: its instructions the
                     organisation's when it has its own

Assigned by LEKA from the server (python -m leka.ops.enterprise), never over
HTTP; read wherever an agent is shown or started: a refusal is the server's,
never only a screen's.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.definition import Definition
from leka.capabilities.models import DedicatedAgent
from leka.capabilities.registry import catalogue


async def dedicated_to(session: AsyncSession, workspace_id: uuid.UUID) -> frozenset[str]:
    """The agents assigned to this workspace."""
    found = await session.scalars(
        select(DedicatedAgent.key).where(DedicatedAgent.workspace_id == workspace_id)
    )
    return frozenset(found.all())


async def hidden_from(session: AsyncSession, workspace_id: uuid.UUID) -> frozenset[str]:
    """The dedicated agents this workspace may not see: made for others —
    never shown, never run, never named, not even as a workflow's step."""
    assigned = await dedicated_to(session, workspace_id)
    return frozenset(d.key for d in catalogue() if d.dedicated and d.key not in assigned)


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


async def instructions_of(session: AsyncSession, workspace_id: uuid.UUID, key: str) -> str | None:
    """The organisation's own instructions for its agent `key` — None when
    it follows the registry's (2026-10-25)."""
    found = await session.scalar(
        select(DedicatedAgent.instructions).where(
            DedicatedAgent.workspace_id == workspace_id, DedicatedAgent.key == key
        )
    )
    return found or None


async def instruct(
    session: AsyncSession, workspace_id: uuid.UUID, key: str, instructions: str | None
) -> bool:
    """Its own instructions given — None: back to the registry's. True when
    they changed; False too when `key` is not dedicated to it."""
    if await instructions_of(session, workspace_id, key) == (instructions or None):
        return False
    done = await session.execute(
        update(DedicatedAgent)
        .where(DedicatedAgent.workspace_id == workspace_id, DedicatedAgent.key == key)
        .values(instructions=instructions or None)
    )
    return bool(getattr(done, "rowcount", 0))


async def own_definition(
    session: AsyncSession, workspace_id: uuid.UUID, definition: Definition
) -> Definition:
    """The agent as it runs for this workspace: its organisation's own
    instructions in place of the registry's when it has them (an
    organisation's architect, its template, its spaces, its directory) —
    everything else the registry's."""
    if not definition.dedicated:
        return definition
    own = await instructions_of(session, workspace_id, definition.key)
    return replace(definition, instructions=own) if own else definition


__all__ = [
    "assign",
    "dedicated_to",
    "instruct",
    "instructions_of",
    "own_definition",
    "unassign",
]
