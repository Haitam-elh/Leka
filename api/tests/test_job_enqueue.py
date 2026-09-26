"""Putting runs on the queue, and repairing what the queue lost.

LEKA-334. A run is durable in the database before anyone tells Redis about it, so most of this
file is about the gap between the two: a queue that refuses the message leaves a run saying it
was never enqueued; the enqueue pass stops at the first refusal instead of timing out on every
run; a due retry, an expired lease and a run Redis forgot are each found by a pass, because none
of them can be found by the thing that went wrong.

Written before the code, and run to watch it fail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import (
    JobQueue,
    JobStatus,
    enqueue_job,
)
from leka.background import jobs as queue_module
from leka.background.tasks import enqueue_pending_runs, recover_runs
from tests.job_run_helpers import PATH, insert_run, make_workspace, row_of, status_of

pytestmark = pytest.mark.integration


class FakeQueue:
    def __init__(self, *, down: bool = False) -> None:
        self.down = down
        self.jobs: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def enqueue(self, job: str, *args: Any, **kwargs: Any) -> None:
        if self.down:
            msg = "Error 61 connecting to localhost:6379. Connection refused."
            raise ConnectionError(msg)
        self.jobs.append((job, args, kwargs))


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> FakeQueue:
    fake = FakeQueue()
    monkeypatch.setattr(queue_module, "_queue", fake)
    monkeypatch.setattr(queue_module, "_named_queues", {})
    return fake


# ── The shape of the state machine ────────────────────────────────────────


# ── Claiming: exactly one worker wins ─────────────────────────────────────


# ── Finishing ─────────────────────────────────────────────────────────────


# ── Failing, and trying again ─────────────────────────────────────────────


# ── Recovery: a worker that died ──────────────────────────────────────────


# ── Creating a run ────────────────────────────────────────────────────────


# ── Enqueueing ────────────────────────────────────────────────────────────


async def test_enqueue_job_records_the_run_and_puts_it_on_the_queue(
    session: AsyncSession, queue: FakeQueue
) -> None:
    workspace = await make_workspace(session)
    await session.commit()

    run = await enqueue_job(f"{PATH}.succeed", "x", for_workspace_id=workspace)

    assert run is not None
    assert [(job, args) for job, args, _ in queue.jobs] == [
        ("leka.background.runner.execute", (str(run.id),))
    ]
    assert (await row_of(session, run.id))["enqueued_at"] is not None


async def test_a_long_job_is_given_its_own_time_and_the_rest_two_hours(
    session: AsyncSession, queue: FakeQueue
) -> None:
    """A sync may read for hours (leka/background/runner.py, RQ_JOB_TIMEOUTS)."""
    workspace = await make_workspace(session)
    await session.commit()

    await enqueue_job(f"{PATH}.succeed", for_workspace_id=workspace)
    await enqueue_job(
        "leka.ingestion.sync.run_sync", str(workspace), str(workspace), for_workspace_id=workspace
    )

    assert [kwargs["job_timeout"] for _, _, kwargs in queue.jobs] == [7200, 12 * 3600]


def test_every_long_job_names_a_real_function() -> None:
    from leka.background.runner import RQ_JOB_TIMEOUTS, _resolve

    for job in RQ_JOB_TIMEOUTS:
        assert callable(_resolve(job)), job


async def test_enqueue_job_refuses_a_second_run_for_the_same_key(
    session: AsyncSession, queue: FakeQueue
) -> None:
    workspace = await make_workspace(session)
    await session.commit()

    first = await enqueue_job(
        f"{PATH}.succeed", for_workspace_id=workspace, concurrency_key="sync:1"
    )
    second = await enqueue_job(
        f"{PATH}.succeed", for_workspace_id=workspace, concurrency_key="sync:1"
    )

    assert first is not None
    assert second is None
    assert len(queue.jobs) == 1


async def test_a_run_the_queue_would_not_take_is_kept_and_offered_again(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety net for jobs: Redis down at the wrong minute loses nothing,
    because the run is already a row and the row says it was never enqueued."""
    workspace = await make_workspace(session)
    await session.commit()
    monkeypatch.setattr(queue_module, "_queue", FakeQueue(down=True))
    monkeypatch.setattr(queue_module, "_named_queues", {})

    run = await enqueue_job(f"{PATH}.succeed", for_workspace_id=workspace)

    assert run is not None
    assert (await row_of(session, run.id))["enqueued_at"] is None

    recovered = FakeQueue()
    monkeypatch.setattr(queue_module, "_queue", recovered)
    await enqueue_pending_runs()

    assert [args for _, args, _ in recovered.jobs] == [(str(run.id),)]
    assert (await row_of(session, run.id))["enqueued_at"] is not None


async def test_a_priority_run_goes_to_its_own_queue(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = await make_workspace(session)
    await session.commit()
    seen: list[str] = []

    class Named(FakeQueue):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

        def enqueue(self, job: str, *args: Any, **kwargs: Any) -> None:
            seen.append(self.name)

    monkeypatch.setattr(queue_module, "_queue", Named("leka"))
    monkeypatch.setattr(queue_module, "_named_queues", {"leka:high": Named("leka:high")})

    await enqueue_job(f"{PATH}.succeed", for_workspace_id=workspace, queue=JobQueue.HIGH)

    assert seen == ["leka:high"]


async def test_the_queue_going_down_stops_the_pass_rather_than_trying_every_run(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = await make_workspace(session)
    first = await insert_run(session, workspace)
    second = await insert_run(session, workspace)
    await session.commit()
    down = FakeQueue(down=True)
    monkeypatch.setattr(queue_module, "_queue", down)
    monkeypatch.setattr(queue_module, "_named_queues", {})

    result = await enqueue_pending_runs()

    assert result["enqueued"] == 0
    assert result["queue_down"] == 1
    assert (await row_of(session, first))["enqueued_at"] is None
    assert (await row_of(session, second))["enqueued_at"] is None


async def test_recover_runs_does_all_three_repairs(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    lost_worker = await insert_run(
        session,
        workspace,
        status=JobStatus.RUNNING,
        attempts=1,
        locked_until=datetime.now(UTC) - timedelta(minutes=1),
    )
    due_retry = await insert_run(
        session,
        workspace,
        status=JobStatus.RETRYING,
        attempts=1,
        next_run_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await session.commit()

    result = await recover_runs()

    assert result["leases_expired"] >= 1
    assert result["retries_promoted"] >= 1
    assert await status_of(session, due_retry) is JobStatus.QUEUED
    # the lost worker's retry is not due for another 30 seconds: still waiting
    assert await status_of(session, lost_worker) is JobStatus.RETRYING


# ── The runner ────────────────────────────────────────────────────────────


# ── History: what a customer may see ──────────────────────────────────────
