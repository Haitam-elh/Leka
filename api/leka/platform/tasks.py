"""Background work for the platform: finishing what a deletion started.

THE TRAP THIS FILE EXISTS FOR. `ON DELETE CASCADE` removes a customer's ROWS
when their workspace goes. It does not, and cannot, remove their OBJECTS —
nothing in PostgreSQL reaches a bucket. Without what is written here,
deleting a customer leaves their payloads with us for ever: a GDPR failure,
because the erasure did not actually happen, and a bill that grows for data
nobody will ever read.

Two mechanisms, and both are needed rather than either.

    erase()  enqueues a prefix purge      — fast, and where the intent is
    reconciliation  finds what is left    — slow, and where the truth is

A queue can lose a message, a worker can die between two objects, a Redis
can be down at exactly the wrong minute. The purge is the answer for the
ordinary case; the reconciliation sweep in leka.ingestion.tasks is what makes
the guarantee true rather than likely.

Run by hand, or by whatever drives the background loop:

    python -m leka.platform.tasks
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from leka.db import load_schema, session_factory, system_scope
from leka.platform.models import Workspace, WorkspaceStatus
from leka.platform.service import DELETION_GRACE_PERIOD
from leka.platform.storage import object_store, workspace_prefix

logger = structlog.get_logger(__name__)


async def purge_workspace_objects(workspace_id: str) -> int:
    """Delete every stored object belonging to one workspace.

    A prefix delete, which is the whole reason the workspace id is the first
    segment of every key: erasing a customer is one call rather than a walk
    of the entire store asking who owns what.

    Takes a string because RQ serialises arguments to JSON and a UUID is not
    one. Converting here, at the boundary, beats every caller remembering.

    Safe to run twice. A prefix that is already empty removes nothing and
    says so, which is what lets the reconciliation sweep call this without
    having to know whether the first attempt worked.
    """
    workspace_uuid = uuid.UUID(workspace_id)
    removed = await object_store().delete_prefix(workspace_prefix(workspace_uuid))
    logger.info("workspace_objects_purged", workspace_id=workspace_id, objects=removed)
    return removed


async def erase_workspaces_past_grace(*, now: datetime | None = None) -> dict[str, int]:
    """Erase the workspaces whose grace period has run out.

    LEKA-331 gave a deletion request a grace period: access stops at once,
    the data stays, and a customer who changes their mind within
    DELETION_GRACE_PERIOD loses nothing. Nothing was ever wired up to end
    that period, so `erase()` had no caller and a requested deletion never
    actually happened. This is that caller.

    system_scope because it is exactly what that exists for: work that spans
    every tenant, declared in one line a reviewer can see.

    The rows go first and the objects after — deliberately, and not the other
    way round. An object nobody speaks for is found by reconciliation and
    removed; a row pointing at bytes that are already gone is a broken read
    with nothing left to repair it from.
    """
    moment = now or datetime.now(UTC)
    cutoff = moment - DELETION_GRACE_PERIOD
    erased: list[str] = []

    with system_scope():
        async with session_factory() as session:
            due = await session.execute(
                select(Workspace)
                .where(Workspace.status == WorkspaceStatus.PENDING_DELETION)
                .where(Workspace.deletion_requested_at.is_not(None))
                .where(Workspace.deletion_requested_at <= cutoff)
            )
            for workspace in due.scalars().all():
                workspace_id = str(workspace.id)
                await session.delete(workspace)
                erased.append(workspace_id)
            await session.commit()

    # Only once the rows are committed. Deleting the bytes of a transaction
    # that then rolls back would destroy data belonging to a workspace that
    # still exists.
    objects = 0
    for workspace_id in erased:
        objects += await purge_workspace_objects(workspace_id)

    result = {"workspaces": len(erased), "objects": objects}
    logger.info("workspace_erasure_completed", **result)
    return result


def run_purge_workspace_objects(workspace_id: str) -> int:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(purge_workspace_objects(workspace_id))


def run_erase_workspaces_past_grace() -> dict[str, int]:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(erase_workspaces_past_grace())


if __name__ == "__main__":  # pragma: no cover
    load_schema()  # every table, as the API has (leka/schema.py)
    run_erase_workspaces_past_grace()
