"""Publishing an event, and handing it to the queue.

LEKA-334. The outbox is worth what its failure modes are worth, so most of this
file is about them: Redis down, an event nobody consumes, two dispatchers at
once, a caller whose transaction rolls back.

Written before the code, and run to watch it fail.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import Event, EventStatus, publish_event
from leka.background import jobs as queue_module
from leka.background import routes as routes_module
from leka.background.repository import EventDispatchRepository, JobRunRepository
from leka.background.routes import Route
from leka.background.tasks import dispatch_pending_events
from leka.core.config import Settings
from leka.core.request_context import reset_request_id, set_request_id
from leka.db import session_factory, system_scope
from leka.platform import Workspace

pytestmark = pytest.mark.integration

JOB = "tests.example.handle_event"

VALID = {
    "database_url": "postgresql+asyncpg://leka:leka@127.0.0.1:5432/leka",
    "redis_url": "redis://127.0.0.1:6379/0",
    "secret_key": "not-a-real-secret",
    "encryption_keys": ["MN3nrX7VP5Mj0SRB4G-pIPOrvlCyT-CQoBZvsQFYHss="],
}


class FakeQueue:
    """Records what would have been enqueued. Optionally refuses."""

    def __init__(self, *, down: bool = False) -> None:
        self.down = down
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []

    def enqueue(self, job: str, *args: Any, **kwargs: Any) -> None:
        if self.down:
            msg = "Error 61 connecting to localhost:6379. Connection refused."
            raise ConnectionError(msg)
        self.jobs.append((job, args))


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> FakeQueue:
    fake = FakeQueue()
    monkeypatch.setattr(queue_module, "_queue", fake)
    return fake


@pytest.fixture
def routed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setitem(routes_module.ROUTES, "test.happened", (Route(JOB),))
    yield


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


async def _load(event_id: uuid.UUID) -> Event:
    with system_scope():
        async with session_factory() as fresh:
            return (await fresh.execute(select(Event).where(Event.id == event_id))).scalar_one()


# ── Publishing ────────────────────────────────────────────────────────────


# ── Dispatching ───────────────────────────────────────────────────────────
#
# The dispatcher writes to the database and nothing else. Whether Redis is up is
# a question for the enqueue pass (tests/test_job_runs.py); none of these tests
# should ever need a queue, and the `queue` fixture is there to prove none is used.


async def _runs_for(event_id: uuid.UUID) -> list[dict[str, Any]]:
    async with session_factory() as fresh:
        rows = await fresh.execute(
            text(
                "SELECT job, args, for_workspace_id, request_id, queue, status, enqueued_at "
                "FROM job_runs WHERE event_id = :e ORDER BY created_at"
            ),
            {"e": event_id},
        )
        return [dict(row) for row in rows.mappings()]


@pytest.mark.usefixtures("routed")
async def test_a_pending_event_becomes_a_job_run_and_is_marked_runs_created(
    session: AsyncSession, queue: FakeQueue
) -> None:
    workspace = await _workspace(session)
    token = set_request_id("01WHOCLICKED")
    try:
        event_id = await _published(session, workspace)
    finally:
        reset_request_id(token)

    await dispatch_pending_events()

    (run,) = await _runs_for(event_id)
    assert run["job"] == JOB
    assert run["args"] == [str(event_id)]
    assert run["for_workspace_id"] == workspace
    assert run["request_id"] == "01WHOCLICKED"
    assert (run["queue"], run["status"], run["enqueued_at"]) == ("leka", "queued", None)
    stored = await _load(event_id)
    assert stored.status is EventStatus.RUNS_CREATED
    assert stored.runs_created_at is not None
    assert queue.jobs == [], "the dispatcher must not touch Redis"


@pytest.mark.usefixtures("routed")
async def test_a_route_can_name_the_queue_its_job_goes_on(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, queue: FakeQueue
) -> None:
    from leka.background import JobQueue

    monkeypatch.setitem(
        routes_module.ROUTES, "test.urgent", (Route(JOB, JobQueue.HIGH), Route(f"{JOB}_2"))
    )
    event_id = await _published(session, await _workspace(session), "test.urgent")

    await dispatch_pending_events()

    runs = await _runs_for(event_id)
    assert sorted((run["job"], run["queue"]) for run in runs) == [
        (JOB, "leka:high"),
        (f"{JOB}_2", "leka"),
    ]


@pytest.mark.usefixtures("routed")
async def test_an_event_whose_runs_exist_is_not_dispatched_again(
    session: AsyncSession, queue: FakeQueue
) -> None:
    event_id = await _published(session, await _workspace(session))
    await dispatch_pending_events()
    await dispatch_pending_events()

    assert len(await _runs_for(event_id)) == 1


@pytest.mark.usefixtures("routed")
async def test_dispatching_the_same_event_twice_still_yields_one_run(
    session: AsyncSession, queue: FakeQueue
) -> None:
    """The dispatcher can die after creating the runs and before marking the
    event. The next pass starts from `pending` again — and unique (event, job)
    is what makes that a refusal rather than a second execution."""
    event_id = await _published(session, await _workspace(session))
    await dispatch_pending_events()
    async with session_factory() as fixup, fixup.begin():
        await fixup.execute(
            text("UPDATE events SET status = 'pending', runs_created_at = NULL WHERE id = :e"),
            {"e": event_id},
        )

    await dispatch_pending_events()

    assert len(await _runs_for(event_id)) == 1
    assert (await _load(event_id)).status is EventStatus.RUNS_CREATED


@pytest.mark.usefixtures("routed")
async def test_events_become_runs_oldest_first(session: AsyncSession, queue: FakeQueue) -> None:
    workspace = await _workspace(session)
    first = await _published(session, workspace)
    second = await _published(session, workspace)

    await dispatch_pending_events()

    async with session_factory() as fresh:
        rows = await fresh.execute(
            text(
                "SELECT event_id FROM job_runs WHERE event_id IN (:a, :b) ORDER BY created_at, id"
            ),
            {"a": first, "b": second},
        )
        assert [row[0] for row in rows] == [first, second]


async def test_an_event_nobody_consumes_fails_loudly(
    session: AsyncSession, queue: FakeQueue
) -> None:
    """Dropping it silently would look exactly like it working."""
    event_id = await _published(session, await _workspace(session), "nobody.listens")

    await dispatch_pending_events()

    stored = await _load(event_id)
    assert stored.status is EventStatus.FAILED
    assert stored.last_error is not None
    assert "no route" in stored.last_error
    assert await _runs_for(event_id) == []


@pytest.mark.usefixtures("routed")
async def test_a_queue_that_is_down_does_not_hold_up_dispatch(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of putting Redis in another pass: an event is dispatched the
    moment its runs are durable. The run says it has not reached the queue, and
    the enqueue pass takes it when Redis is back."""
    dead = FakeQueue(down=True)
    monkeypatch.setattr(queue_module, "_queue", dead)
    event_id = await _published(session, await _workspace(session))

    await dispatch_pending_events()

    assert (await _load(event_id)).status is EventStatus.RUNS_CREATED
    (run,) = await _runs_for(event_id)
    assert run["enqueued_at"] is None


@pytest.mark.usefixtures("routed")
async def test_an_event_that_keeps_failing_is_given_up_on(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, queue: FakeQueue
) -> None:
    event_id = await _published(session, await _workspace(session))

    async def broken(self: JobRunRepository, **_: object) -> None:
        msg = "the database said no"
        raise RuntimeError(msg)

    monkeypatch.setattr(JobRunRepository, "create", broken)

    for _ in range(3):
        await dispatch_pending_events(max_attempts=3)

    stored = await _load(event_id)
    assert stored.status is EventStatus.FAILED
    assert stored.dispatch_attempts == 3
    assert stored.last_error is not None
    assert "the database said no" in stored.last_error


@pytest.mark.usefixtures("routed")
async def test_one_poisoned_event_does_not_hold_up_the_rest_of_the_batch(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, queue: FakeQueue
) -> None:
    workspace = await _workspace(session)
    poisoned = await _published(session, workspace)
    healthy = await _published(session, workspace)
    real_create = JobRunRepository.create

    async def create(self: JobRunRepository, **kwargs: Any) -> Any:
        if kwargs["event_id"] == poisoned:
            msg = "this event is broken"
            raise RuntimeError(msg)
        return await real_create(self, **kwargs)

    monkeypatch.setattr(JobRunRepository, "create", create)

    await dispatch_pending_events()

    assert (await _load(poisoned)).status is EventStatus.PENDING
    assert (await _load(poisoned)).dispatch_attempts == 1
    assert (await _load(healthy)).status is EventStatus.RUNS_CREATED
    assert len(await _runs_for(healthy)) == 1


@pytest.mark.usefixtures("routed")
async def test_two_dispatchers_never_take_the_same_event(
    session: AsyncSession, queue: FakeQueue
) -> None:
    """FOR UPDATE SKIP LOCKED. Without it two dispatchers both take the same
    event — harmless here because of unique (event, job), but wasted work and
    a lock wait, and not something to lean on by accident."""
    event_id = await _published(session, await _workspace(session))

    with system_scope():
        async with session_factory() as first, session_factory() as second:
            taken = await EventDispatchRepository(first).claim_pending(limit=100)
            assert event_id in {event.id for event in taken}

            competing = await EventDispatchRepository(second).claim_pending(limit=100)
            assert event_id not in {event.id for event in competing}


# ── Retention ─────────────────────────────────────────────────────────────


# ── The route table ───────────────────────────────────────────────────────


def _resolves(dotted_path: str) -> bool:
    import importlib

    module_name, _, function = dotted_path.rpartition(".")
    try:
        return callable(getattr(importlib.import_module(module_name), function, None))
    except ImportError:
        return False


def test_every_declared_route_names_a_real_function() -> None:
    """Self-activating: a route added in six months is checked the day it is
    added. A job named by string is exactly the kind of thing that survives a
    rename and then fails in a worker at three in the morning."""
    broken = {
        event_type: [route.job for route in routes if not _resolves(route.job)]
        for event_type, routes in routes_module.ROUTES.items()
    }
    assert not any(broken.values()), f"routes naming a function that does not exist: {broken}"


def test_the_route_check_can_actually_fail() -> None:
    """ROUTES is empty until the first connector consumes something, which
    makes the test above vacuous today. This proves the checker itself."""
    assert _resolves("leka.identity.tasks.run_purge")
    assert not _resolves("leka.identity.tasks.does_not_exist")
    assert not _resolves("leka.nowhere.tasks.run")


# ── Settings ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "override",
    [
        {"dispatch_batch_size": 0},
        {"dispatch_batch_size": 5000},
        {"dispatch_max_attempts": 0},
    ],
)
def test_a_dispatch_setting_out_of_bounds_is_refused(override: dict[str, int]) -> None:
    """0 attempts reads as "disabled" to whoever types it and "never try" to the
    code, so it is refused rather than given a meaning."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **VALID, **override)  # type: ignore[arg-type]
