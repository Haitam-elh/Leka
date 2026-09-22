"""What the database refuses to store about events.

LEKA-334. The background loop's guarantees — a webhook delivered twice is one
event, an event belongs to exactly one workspace — are only worth anything if
PostgreSQL is what holds them. Application code that "checks first" has a race
between the check and the write; a constraint does not.

Written before the table existed, and run to watch every one of them fail.
Most of it talks SQL rather than the model on purpose: the invariants belong to
the schema, and a test through the ORM would be measuring the ORM. One test
goes through the model, to prove the two agree.

Nothing here commits. The `session` fixture rolls back.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine.interfaces import ReflectedColumn
from sqlalchemy.exc import IntegrityError, NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import Event, EventStatus
from leka.db import engine, workspace_scope
from leka.platform import Workspace

pytestmark = pytest.mark.integration

EVENT_COLUMNS = {
    "id",
    "workspace_id",
    "type",
    "payload",
    "dedupe_key",
    "request_id",
    "status",
    "dispatch_attempts",
    "last_error",
    "runs_created_at",
    "created_at",
    "updated_at",
}


async def _workspace(session: AsyncSession) -> uuid.UUID:
    workspace = Workspace(name="bg", slug=f"bg-{uuid.uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    return workspace.id


async def _event(
    session: AsyncSession, workspace_id: uuid.UUID, *, key: str | None = None
) -> uuid.UUID:
    result = await session.execute(
        text(
            "INSERT INTO events (workspace_id, type, dedupe_key) "
            "VALUES (:w, 'source.sync_requested', :k) RETURNING id"
        ),
        {"w": workspace_id, "k": key},
    )
    identifier: uuid.UUID = result.scalar_one()
    return identifier


async def _refused(session: AsyncSession, statement: str, **params: object) -> None:
    """The database must reject this. A savepoint keeps the session usable."""
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(text(statement), params)


async def _columns(table: str) -> dict[str, ReflectedColumn]:
    async with engine.connect() as connection:
        try:
            return await connection.run_sync(
                lambda sync: {column["name"]: column for column in inspect(sync).get_columns(table)}
            )
        except NoSuchTableError:
            pytest.fail(f"table {table!r} does not exist")


# ── Shape ─────────────────────────────────────────────────────────────────


async def test_events_has_the_columns_the_design_names() -> None:
    assert set(await _columns("events")) == EVENT_COLUMNS


async def test_events_workspace_id_is_not_nullable() -> None:
    assert (await _columns("events"))["workspace_id"]["nullable"] is False


# ── Behaviour ─────────────────────────────────────────────────────────────


async def test_an_event_starts_pending_with_no_dispatch_attempts(session: AsyncSession) -> None:
    workspace = await _workspace(session)
    event = await _event(session, workspace)

    row = (
        await session.execute(
            text("SELECT status, dispatch_attempts, runs_created_at FROM events WHERE id = :i"),
            {"i": event},
        )
    ).one()
    assert tuple(row) == ("pending", 0, None)


async def test_the_model_and_the_migration_agree(session: AsyncSession) -> None:
    """Through the ORM, so a mapping that drifted from the table shows here.

    The typed status is the part worth checking: the column holds the enum
    VALUE, and a mismatch only surfaces at the first insert.
    """
    workspace = await _workspace(session)

    with workspace_scope(workspace):
        event = Event(
            workspace_id=workspace,
            type="source.sync_requested",
            payload={"source_id": "abc", "full": False},
            dedupe_key="github:delivery:7",
        )
        session.add(event)
        await session.flush()
        await session.refresh(event)

    assert event.status is EventStatus.PENDING
    assert event.dispatch_attempts == 0
    assert event.payload == {"source_id": "abc", "full": False}
    assert event.request_id is None


# ── Deduplication ─────────────────────────────────────────────────────────


async def test_the_same_dedupe_key_is_refused_within_a_workspace(session: AsyncSession) -> None:
    """A webhook delivered twice must become one event."""
    workspace = await _workspace(session)
    await _event(session, workspace, key="github:delivery:42")

    await _refused(
        session,
        "INSERT INTO events (workspace_id, type, dedupe_key) "
        "VALUES (:w, 'x', 'github:delivery:42')",
        w=workspace,
    )


async def test_the_same_dedupe_key_is_allowed_in_another_workspace(session: AsyncSession) -> None:
    """Two customers may legitimately produce the same key. It must not be a
    way of learning that another customer has already seen it."""
    first = await _workspace(session)
    second = await _workspace(session)
    await _event(session, first, key="github:delivery:42")
    await _event(session, second, key="github:delivery:42")


async def test_events_without_a_dedupe_key_never_collide(session: AsyncSession) -> None:
    workspace = await _workspace(session)
    await _event(session, workspace)
    await _event(session, workspace)


# ── Closed sets and bounds ────────────────────────────────────────────────


async def test_an_event_status_outside_the_closed_set_is_refused(session: AsyncSession) -> None:
    workspace = await _workspace(session)
    await _refused(
        session,
        "INSERT INTO events (workspace_id, type, status) VALUES (:w, 'x', 'bogus')",
        w=workspace,
    )


async def test_an_event_must_have_a_type(session: AsyncSession) -> None:
    workspace = await _workspace(session)
    await _refused(
        session,
        "INSERT INTO events (workspace_id, type) VALUES (:w, '')",
        w=workspace,
    )


async def test_dispatch_attempts_cannot_be_negative(session: AsyncSession) -> None:
    workspace = await _workspace(session)
    await _refused(
        session,
        "INSERT INTO events (workspace_id, type, dispatch_attempts) VALUES (:w, 'x', -1)",
        w=workspace,
    )


# ── Tenancy ───────────────────────────────────────────────────────────────


async def test_deleting_a_workspace_deletes_its_events(session: AsyncSession) -> None:
    """Erasing a customer erases what was recorded about them."""
    workspace = await _workspace(session)
    event = await _event(session, workspace)

    await session.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace})

    remaining = await session.execute(
        text("SELECT count(*) FROM events WHERE id = :e"), {"e": event}
    )
    assert remaining.scalar_one() == 0
