"""Publishing an event.

LEKA-334. An event is written into the CALLER'S session, so it commits with the change
that caused it and rolls back with it — the whole point of an outbox. Most of this file
is that, and what a malformed or duplicated event does at the door.

Written before the code, and run to watch it fail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import Event, EventStatus, publish_event
from leka.core.request_context import reset_request_id, set_request_id
from leka.db import session_factory, system_scope
from leka.platform import Workspace

pytestmark = pytest.mark.integration


async def _workspace(session: AsyncSession) -> uuid.UUID:
    workspace = Workspace(name="ev", slug=f"ev-{uuid.uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    return workspace.id


# ── Publishing ────────────────────────────────────────────────────────────


async def test_publishing_writes_a_pending_event(session: AsyncSession) -> None:
    workspace = await _workspace(session)

    event = await publish_event(session, workspace, "source.sync_requested", {"source": "abc"})

    assert event is not None
    assert (event.status, event.payload, event.dispatch_attempts) == (
        EventStatus.PENDING,
        {"source": "abc"},
        0,
    )


async def test_publishing_records_the_request_that_caused_it(session: AsyncSession) -> None:
    """The thread that joins "the user clicked" to "the worker crashed"."""
    workspace = await _workspace(session)
    token = set_request_id("01TESTREQUESTID")
    try:
        event = await publish_event(session, workspace, "test.happened")
    finally:
        reset_request_id(token)

    assert event is not None
    assert event.request_id == "01TESTREQUESTID"


async def test_an_event_published_outside_a_request_has_no_request_id(
    session: AsyncSession,
) -> None:
    event = await publish_event(session, await _workspace(session), "test.happened")

    assert event is not None
    assert event.request_id is None


async def test_publishing_the_same_dedupe_key_twice_yields_one_event(
    session: AsyncSession,
) -> None:
    """A webhook delivered twice. The second is refused, and says so by
    returning None rather than raising: a duplicate is not an error."""
    workspace = await _workspace(session)

    first = await publish_event(session, workspace, "test.happened", dedupe_key="delivery:1")
    second = await publish_event(session, workspace, "test.happened", dedupe_key="delivery:1")

    assert first is not None
    assert second is None
    count = await session.execute(
        text("SELECT count(*) FROM events WHERE workspace_id = :w"), {"w": workspace}
    )
    assert count.scalar_one() == 1


async def test_an_event_is_lost_with_the_transaction_that_wrote_it(
    session: AsyncSession,
) -> None:
    """The point of an outbox: the event exists if and only if the change does."""
    workspace = await _workspace(session)
    await session.commit()

    event = await publish_event(session, workspace, "test.happened")
    assert event is not None
    event_id = event.id
    await session.rollback()

    with system_scope():
        async with session_factory() as fresh:
            found = (
                await fresh.execute(select(Event).where(Event.id == event_id))
            ).scalar_one_or_none()
    assert found is None


@pytest.mark.parametrize("bad_type", ["", "Has Spaces", "UPPER.case", "x" * 101, "trailing."])
async def test_a_malformed_event_type_is_refused(session: AsyncSession, bad_type: str) -> None:
    workspace = await _workspace(session)
    with pytest.raises(ValueError, match="event type"):
        await publish_event(session, workspace, bad_type)


async def test_an_oversized_payload_is_refused(session: AsyncSession) -> None:
    """Events say WHAT happened, never the data. Raw material goes to the
    object store (ADR 010); an outbox row is not where it lives."""
    workspace = await _workspace(session)
    with pytest.raises(ValueError, match="payload"):
        await publish_event(session, workspace, "test.happened", {"blob": "x" * 20_000})


async def test_a_payload_that_is_not_json_is_refused(session: AsyncSession) -> None:
    """A datetime or a UUID would fail deep inside the driver, at flush time,
    with a message about serialisation. Better to say so where it was written."""
    workspace = await _workspace(session)
    with pytest.raises(ValueError, match="JSON"):
        await publish_event(session, workspace, "test.happened", {"at": datetime.now(UTC)})


# ── Dispatching ───────────────────────────────────────────────────────────
#
# The dispatcher writes to the database and nothing else. Whether Redis is up is
# a question for the enqueue pass (tests/test_job_runs.py); none of these tests
# should ever need a queue, and the `queue` fixture is there to prove none is used.


# ── Retention ─────────────────────────────────────────────────────────────


# ── The route table ───────────────────────────────────────────────────────


# ── Settings ──────────────────────────────────────────────────────────────
