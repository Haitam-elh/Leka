"""The transitions of a job run, and the passes that repair what they cannot.

LEKA-334. Every transition is ONE statement with the state it expects in its WHERE, and says
whether it changed anything: that is the whole concurrency story, so most of this file is
about two things racing — two workers for one run, a worker and recovery — and about what a
dead worker, a failed attempt and a queue that forgot each leave behind.

The state machine's SHAPE is asserted in tests/test_job_run_states.py. Here: that the
repository only ever moves a run along an edge it declares, from every status, with every
method; and what each edge does.

Written before the code, and run to watch it fail.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import (
    TRANSITIONS,
    JobQueue,
    JobRun,
    JobStatus,
)
from leka.background.repository import JobRunRepository
from leka.db import session_factory
from tests.job_run_helpers import NOW, PATH, insert_run, make_workspace, row_of, status_of

pytestmark = pytest.mark.integration

# ── The shape of the state machine ────────────────────────────────────────


async def test_the_repository_only_moves_a_run_along_a_declared_edge(
    session: AsyncSession,
) -> None:
    """Every transition method, from every status. Whatever it does, the run
    ends where it was or somewhere TRANSITIONS says it may go."""
    workspace = await make_workspace(session)
    repository = JobRunRepository(session)
    past = NOW - timedelta(hours=1)

    actions: dict[str, Callable[[JobRunRepository, uuid.UUID], Awaitable[object]]] = {
        "claim": lambda r, i: r.claim(i, now=NOW, lease_seconds=60),
        "succeed": lambda r, i: r.succeed(i, now=NOW),
        "fail": lambda r, i: r.fail_attempt(
            i, "e", now=NOW, retry_base_seconds=30, retry_max_seconds=3600
        ),
        "fail_permanent": lambda r, i: r.fail_attempt(
            i, "e", now=NOW, retry_base_seconds=30, retry_max_seconds=3600, permanent=True
        ),
        "expire": lambda r, i: r.expire_leases(
            now=NOW, limit=100, retry_base_seconds=30, retry_max_seconds=3600
        ),
        "promote": lambda r, i: r.promote_due_retries(now=NOW, limit=100),
    }

    for start in JobStatus:
        for name, action in actions.items():
            run_id = await insert_run(
                session,
                workspace,
                status=start,
                attempts=1 if start is not JobStatus.QUEUED else 0,
                locked_until=past if start is JobStatus.RUNNING else None,
                next_run_at=past if start is JobStatus.RETRYING else None,
            )
            await action(repository, run_id)
            end = await status_of(session, run_id)
            assert end == start or end in TRANSITIONS[start], (
                f"{name} moved a run {start} -> {end}, which TRANSITIONS does not allow"
            )


# ── Claiming: exactly one worker wins ─────────────────────────────────────


async def test_claiming_a_queued_run_starts_it(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace)

    claimed = await JobRunRepository(session).claim(run_id, now=NOW, lease_seconds=300)

    assert claimed is not None
    row = await row_of(session, run_id)
    assert row["status"] == "running"
    assert row["attempts"] == 1
    assert row["started_at"] == NOW
    assert row["locked_until"] == NOW + timedelta(seconds=300)


@pytest.mark.parametrize("status", [s for s in JobStatus if s is not JobStatus.QUEUED])
async def test_only_a_queued_run_can_be_claimed(session: AsyncSession, status: JobStatus) -> None:
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace, status=status, attempts=1)

    assert await JobRunRepository(session).claim(run_id, now=NOW, lease_seconds=60) is None
    assert await status_of(session, run_id) is status


async def test_claiming_a_run_that_does_not_exist_is_nothing(session: AsyncSession) -> None:
    assert await JobRunRepository(session).claim(uuid.uuid4(), now=NOW, lease_seconds=60) is None


async def test_two_workers_racing_for_one_run_produce_one_winner(session: AsyncSession) -> None:
    """The guarantee of the whole module. RQ delivers at least once, so two
    workers CAN receive the same message; the UPDATE ... WHERE status='queued'
    is what makes only one of them act on it."""
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace)
    await session.commit()

    async def attempt() -> JobRun | None:
        async with session_factory() as own:
            claimed = await JobRunRepository(own).claim(run_id, now=NOW, lease_seconds=60)
            await own.commit()
            return claimed

    results = await asyncio.gather(*(attempt() for _ in range(8)))

    assert sum(result is not None for result in results) == 1
    assert (await row_of(session, run_id))["attempts"] == 1


async def test_a_heartbeat_extends_the_lease_of_a_running_run(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace, status=JobStatus.RUNNING, attempts=1)
    repository = JobRunRepository(session)

    assert await repository.heartbeat(run_id, now=NOW, lease_seconds=120) is True
    assert (await row_of(session, run_id))["locked_until"] == NOW + timedelta(seconds=120)


async def test_a_heartbeat_for_a_run_that_is_no_longer_running_says_so(
    session: AsyncSession,
) -> None:
    """The lease was lost: recovery decided this worker was dead. The worker
    must learn it, not keep renewing a lease it no longer holds."""
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace, status=JobStatus.RETRYING, attempts=1)

    assert await JobRunRepository(session).heartbeat(run_id, now=NOW, lease_seconds=60) is False


# ── Finishing ─────────────────────────────────────────────────────────────


async def test_a_running_run_can_succeed(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    run_id = await insert_run(
        session, workspace, status=JobStatus.RUNNING, attempts=1, locked_until=NOW
    )

    assert await JobRunRepository(session).succeed(run_id, now=NOW) is True

    row = await row_of(session, run_id)
    assert (row["status"], row["finished_at"], row["locked_until"]) == ("succeeded", NOW, None)


async def test_only_a_running_run_can_succeed(session: AsyncSession) -> None:
    """A worker whose lease was lost finishes late. It must not overwrite what
    recovery decided in the meantime."""
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace, status=JobStatus.RETRYING, attempts=1)

    assert await JobRunRepository(session).succeed(run_id, now=NOW) is False
    assert await status_of(session, run_id) is JobStatus.RETRYING


# ── Failing, and trying again ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("attempts", "delay"),
    [(1, 30), (2, 60), (3, 120), (8, 3600), (20, 3600)],
)
async def test_a_failed_attempt_is_retried_after_a_growing_delay(
    session: AsyncSession, attempts: int, delay: int
) -> None:
    """30s, 60s, 120s ... capped at an hour. Not a fixed interval: a downstream
    that is down for a minute should not be hammered every thirty seconds."""
    workspace = await make_workspace(session)
    run_id = await insert_run(
        session, workspace, status=JobStatus.RUNNING, attempts=attempts, max_attempts=50
    )

    await JobRunRepository(session).fail_attempt(
        run_id, "boom", now=NOW, retry_base_seconds=30, retry_max_seconds=3600
    )

    row = await row_of(session, run_id)
    assert row["status"] == "retrying"
    assert row["next_run_at"] == NOW + timedelta(seconds=delay)
    assert row["last_error"] == "boom"
    assert row["locked_until"] is None


async def test_a_run_out_of_attempts_fails_for_good(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    run_id = await insert_run(
        session, workspace, status=JobStatus.RUNNING, attempts=3, max_attempts=3
    )

    await JobRunRepository(session).fail_attempt(
        run_id, "still broken", now=NOW, retry_base_seconds=30, retry_max_seconds=3600
    )

    row = await row_of(session, run_id)
    assert (row["status"], row["finished_at"], row["next_run_at"]) == ("failed", NOW, None)
    assert row["last_error"] == "still broken"


async def test_a_permanent_failure_is_not_retried(session: AsyncSession) -> None:
    """A job path that does not import will not import next time either."""
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace, status=JobStatus.RUNNING, attempts=1)

    await JobRunRepository(session).fail_attempt(
        run_id,
        "no such job",
        now=NOW,
        retry_base_seconds=30,
        retry_max_seconds=3600,
        permanent=True,
    )

    assert await status_of(session, run_id) is JobStatus.FAILED


async def test_an_error_is_stored_truncated(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace, status=JobStatus.RUNNING, attempts=1)

    await JobRunRepository(session).fail_attempt(
        run_id, "x" * 10_000, now=NOW, retry_base_seconds=30, retry_max_seconds=3600
    )

    assert len((await row_of(session, run_id))["last_error"]) <= 2000


async def test_only_a_running_run_can_fail_an_attempt(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace, status=JobStatus.SUCCEEDED, attempts=1)

    result = await JobRunRepository(session).fail_attempt(
        run_id, "late", now=NOW, retry_base_seconds=30, retry_max_seconds=3600
    )

    assert result is None
    assert await status_of(session, run_id) is JobStatus.SUCCEEDED


# ── Recovery: a worker that died ──────────────────────────────────────────


async def test_a_run_whose_lease_expired_is_recovered(session: AsyncSession) -> None:
    """The worker died holding it. Without this the run is `running` for ever,
    and — worse — holds its concurrency key, so nothing else can run."""
    workspace = await make_workspace(session)
    lost = await insert_run(
        session,
        workspace,
        status=JobStatus.RUNNING,
        attempts=1,
        locked_until=NOW - timedelta(seconds=1),
    )
    alive = await insert_run(
        session,
        workspace,
        status=JobStatus.RUNNING,
        attempts=1,
        locked_until=NOW + timedelta(minutes=5),
    )

    recovered = await JobRunRepository(session).expire_leases(
        now=NOW, limit=100, retry_base_seconds=30, retry_max_seconds=3600
    )

    assert recovered >= 1
    lost_row = await row_of(session, lost)
    assert lost_row["status"] == "retrying"
    assert "lease expired" in lost_row["last_error"]
    assert lost_row["next_run_at"] == NOW + timedelta(seconds=30)
    assert await status_of(session, alive) is JobStatus.RUNNING


async def test_a_lost_worker_uses_up_an_attempt(session: AsyncSession) -> None:
    """Otherwise a job that kills its worker every time would be retried for
    ever, and never look like it was failing."""
    workspace = await make_workspace(session)
    run_id = await insert_run(
        session,
        workspace,
        status=JobStatus.RUNNING,
        attempts=3,
        max_attempts=3,
        locked_until=NOW - timedelta(seconds=1),
    )

    await JobRunRepository(session).expire_leases(
        now=NOW, limit=100, retry_base_seconds=30, retry_max_seconds=3600
    )

    assert await status_of(session, run_id) is JobStatus.FAILED


async def test_a_retry_that_is_due_goes_back_on_the_queue(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    due = await insert_run(
        session,
        workspace,
        status=JobStatus.RETRYING,
        attempts=1,
        next_run_at=NOW - timedelta(seconds=1),
        enqueued_at=NOW - timedelta(minutes=2),
    )
    later = await insert_run(
        session,
        workspace,
        status=JobStatus.RETRYING,
        attempts=1,
        next_run_at=NOW + timedelta(minutes=5),
    )

    await JobRunRepository(session).promote_due_retries(now=NOW, limit=100)

    promoted = await row_of(session, due)
    assert (promoted["status"], promoted["enqueued_at"], promoted["next_run_at"]) == (
        "queued",
        None,
        None,
    )
    assert await status_of(session, later) is JobStatus.RETRYING


async def test_a_queued_run_the_queue_forgot_is_offered_again(session: AsyncSession) -> None:
    """Redis was flushed, or restarted without persistence: the row says
    queued and nothing is going to run it. After a while, offer it again — the
    claim makes a duplicate message harmless."""
    workspace = await make_workspace(session)
    forgotten = await insert_run(
        session, workspace, enqueued_at=NOW - timedelta(hours=3), attempts=0
    )
    fresh = await insert_run(session, workspace, enqueued_at=NOW - timedelta(seconds=10))

    await JobRunRepository(session).forget_stale_enqueues(
        older_than=NOW - timedelta(hours=1), limit=100
    )

    assert (await row_of(session, forgotten))["enqueued_at"] is None
    assert (await row_of(session, fresh))["enqueued_at"] == NOW - timedelta(seconds=10)


# ── Creating a run ────────────────────────────────────────────────────────


async def test_a_run_is_created_queued_and_not_yet_enqueued(session: AsyncSession) -> None:
    workspace = await make_workspace(session)

    run = await JobRunRepository(session).create(
        job=f"{PATH}.succeed",
        args=["a"],
        kwargs={"k": 1},
        for_workspace_id=workspace,
        request_id="01REQ",
        queue=JobQueue.HIGH,
        max_attempts=5,
    )

    assert run is not None
    assert (run.status, run.queue, run.max_attempts, run.enqueued_at) == (
        JobStatus.QUEUED,
        JobQueue.HIGH,
        5,
        None,
    )
    assert (run.args, run.kwargs, run.request_id) == (["a"], {"k": 1}, "01REQ")


async def test_creating_a_run_for_an_active_key_says_so_instead_of_raising(
    session: AsyncSession,
) -> None:
    """Two people click "sync" at once: the second is not an error, it is
    already happening."""
    workspace = await make_workspace(session)
    repository = JobRunRepository(session)

    first = await repository.create(
        job=f"{PATH}.succeed", for_workspace_id=workspace, concurrency_key="sync:1"
    )
    second = await repository.create(
        job=f"{PATH}.succeed", for_workspace_id=workspace, concurrency_key="sync:1"
    )

    assert first is not None
    assert second is None


# ── Enqueueing ────────────────────────────────────────────────────────────


# ── The runner ────────────────────────────────────────────────────────────


# ── History: what a customer may see ──────────────────────────────────────


async def test_a_workspace_sees_its_own_runs_newest_first(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    older = await insert_run(session, workspace)
    newer = await insert_run(session, workspace)
    await session.execute(
        text("UPDATE job_runs SET created_at = now() - interval '1 hour' WHERE id = :i"),
        {"i": older},
    )

    page = await JobRunRepository(session).list_for_workspace(workspace, limit=10)

    assert [run.id for run in page.items] == [newer, older]


async def test_a_workspace_never_sees_another_workspaces_runs(session: AsyncSession) -> None:
    mine = await make_workspace(session)
    theirs = await make_workspace(session)
    await insert_run(session, mine)
    their_run = await insert_run(session, theirs)

    page = await JobRunRepository(session).list_for_workspace(mine, limit=50)

    assert their_run not in {run.id for run in page.items}
    assert await JobRunRepository(session).get_for_workspace(mine, their_run) is None


async def test_system_runs_are_never_returned_to_a_workspace(session: AsyncSession) -> None:
    """A retention sweep is operating data, not a customer's. The NULL rows are
    the ones a careless `WHERE for_workspace_id = :w OR for_workspace_id IS
    NULL` would leak, and the reason this filter is explicit."""
    workspace = await make_workspace(session)
    mine = await insert_run(session, workspace)
    system = await insert_run(session, None)

    repository = JobRunRepository(session)
    page = await repository.list_for_workspace(workspace, limit=50)

    assert {run.id for run in page.items} == {mine}
    assert await repository.get_for_workspace(workspace, system) is None


async def test_the_history_can_be_paged_through_completely(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    created = [await insert_run(session, workspace) for _ in range(5)]
    repository = JobRunRepository(session)

    seen: list[uuid.UUID] = []
    cursor: str | None = None
    while True:
        page = await repository.list_for_workspace(workspace, limit=2, cursor=cursor)
        seen.extend(run.id for run in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert sorted(seen) == sorted(created)


def test_the_history_of_no_workspace_is_refused_rather_than_returning_the_system_runs() -> None:
    """`for_workspace_id == None` compiles to IS NULL: exactly the rows this filter exists to
    withhold. A caller that lost its workspace must be stopped, not handed the system's runs."""
    with pytest.raises(ValueError, match="no workspace"):
        JobRunRepository.for_workspace(None)
