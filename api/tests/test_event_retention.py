"""Pruning the outbox.

LEKA-334. An outbox that is never emptied is a table that grows for ever, and one that is
emptied carelessly deletes the one thing worth looking at: an event that was never dispatched.
So settled events go after the retention, and a pending one never does.

Written before the code, and run to watch it fail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import Event, EventStatus, publish_event
from leka.background.tasks import prune_events
from leka.core.config import Settings
from leka.db import session_factory, system_scope
from leka.platform import Workspace

pytestmark = pytest.mark.integration

VALID = {
    "database_url": "postgresql+asyncpg://leka:leka@127.0.0.1:5432/leka",
    "redis_url": "redis://127.0.0.1:6379/0",
    "secret_key": "not-a-real-secret",
    "encryption_keys": ["MN3nrX7VP5Mj0SRB4G-pIPOrvlCyT-CQoBZvsQFYHss="],
}


async def _workspace(session: AsyncSession) -> uuid.UUID:
    workspace = Workspace(name="ev", slug=f"ev-{uuid.uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    return workspace.id


async def _published(
    session: AsyncSession,
    workspace: uuid.UUID,
    event_type: str = "test.happened",
    *,
    key: str | None = None,
) -> uuid.UUID:
    event = await publish_event(session, workspace, event_type, {"n": 1}, dedupe_key=key)
    assert event is not None
    await session.commit()
    return event.id


# ── Publishing ────────────────────────────────────────────────────────────


# ── Dispatching ───────────────────────────────────────────────────────────
#
# The dispatcher writes to the database and nothing else. Whether Redis is up is
# a question for the enqueue pass (tests/test_job_runs.py); none of these tests
# should ever need a queue, and the `queue` fixture is there to prove none is used.


# ── Retention ─────────────────────────────────────────────────────────────


async def test_old_settled_events_are_pruned_and_pending_ones_never_are(
    session: AsyncSession,
) -> None:
    """An outbox that is never emptied is a table that grows for ever. Pending
    events are never touched: an old pending event is a problem to see, not to
    delete."""
    workspace = await _workspace(session)
    old_done = await _published(session, workspace)
    old_failed = await _published(session, workspace)
    old_pending = await _published(session, workspace)
    recent_done = await _published(session, workspace)

    long_ago = datetime.now(UTC) - timedelta(days=400)
    with system_scope():
        async with session_factory() as fixup:
            for identifier, status, created in (
                (old_done, EventStatus.RUNS_CREATED, long_ago),
                (old_failed, EventStatus.FAILED, long_ago),
                (old_pending, EventStatus.PENDING, long_ago),
                (recent_done, EventStatus.RUNS_CREATED, datetime.now(UTC)),
            ):
                await fixup.execute(
                    update(Event)
                    .where(Event.id == identifier)
                    .values(status=status, created_at=created)
                )
            await fixup.commit()

    removed = await prune_events()

    assert removed >= 2
    with system_scope():
        async with session_factory() as fresh:
            remaining = set(
                (
                    await fresh.execute(
                        select(Event.id).where(
                            Event.id.in_([old_done, old_failed, old_pending, recent_done])
                        )
                    )
                ).scalars()
            )
    assert remaining == {old_pending, recent_done}


# ── The route table ───────────────────────────────────────────────────────


# ── Settings ──────────────────────────────────────────────────────────────


def test_a_retention_of_zero_days_is_refused() -> None:
    """0 reads as "keep nothing" to one person and "keep for ever" to another."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **VALID, event_retention_days=0)  # type: ignore[arg-type]
