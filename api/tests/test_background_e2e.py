"""The whole background loop, end to end, on a real Redis and a real RQ worker.

LEKA-334. The other files test each piece with the others held still. This one
lets them move: an event is published, becomes a run, reaches Redis, is picked up
by a worker, and the outcome is read back from the database. And then the things
that go wrong between those steps, each on the path a real failure would take —
a job that fails, a worker that dies, a Redis that loses its memory, a message
delivered twice.

REDIS DATABASE 15, NEVER 0. Queues are named leka, leka:high and leka:low, the
same as a developer's own. A worker running on their machine would consume a test's
jobs, and a test would drain theirs. Database 15 is flushed before and after.

THE WORKER RUNS IN A THREAD, because runner.execute calls asyncio.run and the test
is already inside a loop. RQ's worker installs signal handlers and uses SIGALRM for
timeouts, both main-thread-only, so the test worker turns those two off; nothing
else about it differs from `rq worker`.

Written before the code that was missing (the schedule), and run to watch it fail.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse, urlunparse

import pytest
import redis
from rq import Queue, SimpleWorker
from rq.timeouts import TimerDeathPenalty
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import JobQueue, enqueue_job, publish_event
from leka.background import jobs as queue_module
from leka.background import routes as routes_module
from leka.background.repository import JobRunRepository
from leka.background.routes import Route
from leka.background.tasks import run_maintenance
from leka.core.config import settings
from leka.core.request_context import reset_request_id, set_request_id
from leka.db import session_factory
from leka.platform import Workspace
from tests import background_jobs

pytestmark = pytest.mark.integration

PATH = "tests.background_jobs"
TEST_DATABASE = 15


class ThreadWorker(SimpleWorker):
    """`rq worker`, minus the two things that only work on the main thread."""

    death_penalty_class = TimerDeathPenalty

    def _install_signal_handlers(self) -> None:
        pass


class Rq:
    def __init__(self, connection: redis.Redis) -> None:
        self.connection = connection
        self.queues = {
            JobQueue.HIGH: Queue(JobQueue.HIGH.value, connection=connection),
            JobQueue.DEFAULT: Queue(JobQueue.DEFAULT.value, connection=connection),
            JobQueue.LOW: Queue(JobQueue.LOW.value, connection=connection),
        }

    async def drain(self) -> None:
        """Run every job on the queues, in the order `rq worker` would."""
        worker = ThreadWorker(list(self.queues.values()), connection=self.connection)
        await asyncio.to_thread(worker.work, burst=True)

    def pending(self) -> int:
        return sum(len(queue) for queue in self.queues.values())


@pytest.fixture
def rq(monkeypatch: pytest.MonkeyPatch) -> Iterator[Rq]:
    parsed = urlparse(str(settings.redis_url))
    connection = redis.from_url(urlunparse(parsed._replace(path=f"/{TEST_DATABASE}")))
    connection.flushdb()
    harness = Rq(connection)
    monkeypatch.setattr(queue_module, "_queue", harness.queues[JobQueue.DEFAULT])
    monkeypatch.setattr(
        queue_module,
        "_named_queues",
        {
            JobQueue.HIGH.value: harness.queues[JobQueue.HIGH],
            JobQueue.LOW.value: harness.queues[JobQueue.LOW],
        },
    )
    background_jobs.reset()
    yield harness
    connection.flushdb()
    connection.close()


async def _workspace(session: AsyncSession) -> uuid.UUID:
    workspace = Workspace(name="e2e", slug=f"e2e-{uuid.uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    await session.commit()
    return workspace.id


async def _row(run_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory() as fresh:
        result = await fresh.execute(text("SELECT * FROM job_runs WHERE id = :i"), {"i": run_id})
        return dict(result.mappings().one())


async def _make_retry_due(run_id: uuid.UUID) -> None:
    async with session_factory() as fresh, fresh.begin():
        await fresh.execute(
            text("UPDATE job_runs SET next_run_at = now() - interval '1 second' WHERE id = :i"),
            {"i": run_id},
        )


def _calls(name: str) -> list[Any]:
    return [payload for call, payload in background_jobs.CALLS if call == name]


# ── The happy path ────────────────────────────────────────────────────────


async def test_an_event_reaches_a_worker_and_its_run_succeeds(
    session: AsyncSession, rq: Rq, monkeypatch: pytest.MonkeyPatch
) -> None:
    """publish -> dispatch -> Redis -> worker -> succeeded, with the request that
    caused it visible inside the job."""
    monkeypatch.setitem(routes_module.ROUTES, "workflow.started", (Route(f"{PATH}.record_event"),))
    workspace = await _workspace(session)
    token = set_request_id("01USERCLICKED")
    try:
        event = await publish_event(session, workspace, "workflow.started", {"n": 1})
        assert event is not None
        event_id = event.id
        await session.commit()
    finally:
        reset_request_id(token)

    tick = await run_maintenance()
    assert tick["events"]["runs_created"] >= 1
    assert tick["queue"]["enqueued"] >= 1
    await rq.drain()

    assert _calls("record_event") == [(str(event_id), "01USERCLICKED")]
    async with session_factory() as fresh:
        run = (
            await fresh.execute(
                text("SELECT status, attempts, enqueued_at FROM job_runs WHERE event_id = :e"),
                {"e": event_id},
            )
        ).one()
    assert (run[0], run[1]) == ("succeeded", 1)
    assert run[2] is not None


# ── Failure and retry ─────────────────────────────────────────────────────


async def test_a_job_that_fails_once_is_retried_and_then_succeeds(
    session: AsyncSession, rq: Rq
) -> None:
    workspace = await _workspace(session)
    run = await enqueue_job(f"{PATH}.flaky", "once", 1, for_workspace_id=workspace)
    assert run is not None

    await rq.drain()
    first = await _row(run.id)
    assert (first["status"], first["attempts"]) == ("retrying", 1)
    assert "flaky job 'once' failing" in first["last_error"]

    # The retry waits in the database, not in Redis: nothing is queued.
    assert rq.pending() == 0
    await _make_retry_due(run.id)
    await run_maintenance()
    await rq.drain()

    second = await _row(run.id)
    assert (second["status"], second["attempts"]) == ("succeeded", 2)
    assert len(_calls("flaky")) == 2


async def test_a_job_that_never_works_ends_failed_with_its_error(
    session: AsyncSession, rq: Rq
) -> None:
    workspace = await _workspace(session)
    run = await enqueue_job(f"{PATH}.fail", for_workspace_id=workspace, max_attempts=2)
    assert run is not None

    await rq.drain()
    await _make_retry_due(run.id)
    await run_maintenance()
    await rq.drain()

    final = await _row(run.id)
    assert (final["status"], final["attempts"]) == ("failed", 2)
    assert "boom: the job failed" in final["last_error"]
    assert final["finished_at"] is not None
    # And it stays failed: another pass finds nothing to do for it.
    await run_maintenance()
    await rq.drain()
    assert (await _row(run.id))["status"] == "failed"


# ── A worker that dies ────────────────────────────────────────────────────


async def test_a_run_abandoned_by_a_dead_worker_is_recovered_and_finished(
    session: AsyncSession, rq: Rq
) -> None:
    """A worker claims the run and is killed. Nothing reports it. The lease runs
    out, recovery moves the run on, and another worker finishes the job."""
    from datetime import UTC, datetime, timedelta

    workspace = await _workspace(session)
    run = await enqueue_job(f"{PATH}.label", "survivor", for_workspace_id=workspace)
    assert run is not None
    rq.connection.flushdb()  # the message a dead worker took with it

    async with session_factory() as fresh:
        claimed = await JobRunRepository(fresh).claim(
            run.id, now=datetime.now(UTC) - timedelta(minutes=10), lease_seconds=60
        )
        await fresh.commit()
    assert claimed is not None
    assert (await _row(run.id))["status"] == "running"

    await run_maintenance()
    recovered = await _row(run.id)
    assert recovered["status"] == "retrying"
    assert "lease expired" in recovered["last_error"]

    await _make_retry_due(run.id)
    await run_maintenance()
    await rq.drain()

    final = await _row(run.id)
    assert (final["status"], final["attempts"]) == ("succeeded", 2)
    assert _calls("label") == ["survivor"]


# ── Redis losing its memory ───────────────────────────────────────────────


async def test_a_redis_that_loses_its_memory_loses_no_job(session: AsyncSession, rq: Rq) -> None:
    workspace = await _workspace(session)
    run = await enqueue_job(f"{PATH}.label", "kept", for_workspace_id=workspace)
    assert run is not None
    assert (await _row(run.id))["enqueued_at"] is not None

    rq.connection.flushdb()  # a restart with no persistence
    await rq.drain()
    assert background_jobs.CALLS == [], "the message is gone, so nothing ran"

    # Long enough ago that the run is presumed forgotten rather than just waiting.
    async with session_factory() as fresh, fresh.begin():
        await fresh.execute(
            text("UPDATE job_runs SET enqueued_at = now() - interval '2 hours' WHERE id = :i"),
            {"i": run.id},
        )
    await run_maintenance()
    await rq.drain()

    assert (await _row(run.id))["status"] == "succeeded"
    assert _calls("label") == ["kept"]


# ── Priority ──────────────────────────────────────────────────────────────


async def test_a_worker_takes_high_before_default_before_low(session: AsyncSession, rq: Rq) -> None:
    """Enqueued in the WRONG order on purpose. This is the only priority RQ has,
    and it is what `rq worker leka:high leka leka:low` gives."""
    workspace = await _workspace(session)
    for name, queue in (
        ("low", JobQueue.LOW),
        ("default", JobQueue.DEFAULT),
        ("high", JobQueue.HIGH),
    ):
        assert await enqueue_job(f"{PATH}.label", name, for_workspace_id=workspace, queue=queue)

    await rq.drain()

    assert _calls("label") == ["high", "default", "low"]


# ── Duplicates ────────────────────────────────────────────────────────────


async def test_a_message_delivered_twice_runs_the_job_once(session: AsyncSession, rq: Rq) -> None:
    """RQ is at-least-once. The claim is what makes it once."""
    workspace = await _workspace(session)
    run = await enqueue_job(f"{PATH}.label", "once", for_workspace_id=workspace)
    assert run is not None
    rq.queues[JobQueue.DEFAULT].enqueue("leka.background.runner.execute", str(run.id))
    rq.queues[JobQueue.DEFAULT].enqueue("leka.background.runner.execute", str(run.id))
    assert rq.pending() == 3

    await rq.drain()

    assert _calls("label") == ["once"]
    assert (await _row(run.id))["attempts"] == 1


async def test_a_second_run_for_a_key_waits_until_the_first_is_done(
    session: AsyncSession, rq: Rq
) -> None:
    workspace = await _workspace(session)
    first = await enqueue_job(
        f"{PATH}.label", "a", for_workspace_id=workspace, concurrency_key="sync:1"
    )
    duplicate = await enqueue_job(
        f"{PATH}.label", "b", for_workspace_id=workspace, concurrency_key="sync:1"
    )
    assert first is not None
    assert duplicate is None

    await rq.drain()
    later = await enqueue_job(
        f"{PATH}.label", "c", for_workspace_id=workspace, concurrency_key="sync:1"
    )
    await rq.drain()

    assert later is not None
    assert _calls("label") == ["a", "c"]


async def test_a_workspace_deleted_while_its_job_waits_leaves_nothing_to_run(
    session: AsyncSession, rq: Rq
) -> None:
    """Deleting a customer erases their history with them, so a job that was
    already on the queue finds no run to claim and does nothing."""
    workspace = await _workspace(session)
    run = await enqueue_job(f"{PATH}.label", "orphan", for_workspace_id=workspace)
    assert run is not None
    async with session_factory() as fresh, fresh.begin():
        await fresh.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace})

    await rq.drain()

    assert background_jobs.CALLS == []
