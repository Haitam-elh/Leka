"""Running one job run on a worker: claim it, execute it, record how it went.

LEKA-334. RQ delivers a message at least once, so the runner starts from "someone else may be
doing this too" and settles it with a single UPDATE, not with a check. The interesting parts
are the ones around the job rather than in it: a job that fails and is retried, one that cannot
be imported, five workers receiving one run, a workspace deleted while its job waited, and a
long job that must keep renewing its lease or it would look exactly like a dead worker.

Written before the code, and run to watch it fail.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import (
    JobStatus,
)
from leka.background.repository import JobRunRepository
from leka.background.runner import run_job
from leka.core.request_context import current_request_id, reset_request_id, set_request_id
from leka.db import session_factory
from tests import background_jobs
from tests.job_run_helpers import PATH, insert_run, make_workspace, row_of, status_of

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clean_calls() -> None:
    background_jobs.reset()


# ── The shape of the state machine ────────────────────────────────────────


# ── Claiming: exactly one worker wins ─────────────────────────────────────


# ── Finishing ─────────────────────────────────────────────────────────────


# ── Failing, and trying again ─────────────────────────────────────────────


# ── Recovery: a worker that died ──────────────────────────────────────────


# ── Creating a run ────────────────────────────────────────────────────────


# ── Enqueueing ────────────────────────────────────────────────────────────


# ── The runner ────────────────────────────────────────────────────────────


async def _runnable(
    session: AsyncSession, workspace: uuid.UUID | None, **columns: Any
) -> uuid.UUID:
    run_id = await insert_run(session, workspace, **columns)
    await session.commit()
    return run_id


async def test_running_a_job_calls_it_with_its_arguments_and_records_success(
    session: AsyncSession,
) -> None:
    workspace = await make_workspace(session)
    run_id = await _runnable(session, workspace, args='["a", 2]')

    outcome = await run_job(run_id)

    assert outcome == "succeeded"
    assert background_jobs.CALLS == [("succeed", (("a", 2), {}))]
    assert await status_of(session, run_id) is JobStatus.SUCCEEDED


async def test_a_job_that_raises_is_retried_and_its_error_kept(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    run_id = await _runnable(session, workspace, job=f"{PATH}.fail")

    outcome = await run_job(run_id)

    assert outcome == "retrying"
    row = await row_of(session, run_id)
    assert row["status"] == "retrying"
    assert "boom: the job failed" in row["last_error"]
    assert row["attempts"] == 1
    assert row["next_run_at"] is not None


async def test_a_job_that_keeps_failing_ends_failed(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    run_id = await _runnable(session, workspace, job=f"{PATH}.fail", max_attempts=2)

    assert await run_job(run_id) == "retrying"

    # The retry becomes due and goes back to waiting for a worker.
    async with session_factory() as own:
        await own.execute(
            text("UPDATE job_runs SET next_run_at = now() - interval '1 second' WHERE id = :i"),
            {"i": run_id},
        )
        await own.commit()
    async with session_factory() as own:
        await JobRunRepository(own).promote_due_retries(now=datetime.now(UTC), limit=10)
        await own.commit()

    assert await run_job(run_id) == "failed"
    row = await row_of(session, run_id)
    assert (row["status"], row["attempts"]) == ("failed", 2)


async def test_a_job_that_cannot_be_imported_fails_at_once(session: AsyncSession) -> None:
    """A typo in a job path will not fix itself on the second attempt."""
    workspace = await make_workspace(session)
    run_id = await _runnable(session, workspace, job="tests.background_jobs.does_not_exist")

    assert await run_job(run_id) == "failed"
    row = await row_of(session, run_id)
    assert row["attempts"] == 1
    assert "does_not_exist" in row["last_error"]


async def test_something_that_is_not_callable_fails_at_once(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    run_id = await _runnable(session, workspace, job=f"{PATH}.not_a_function")

    assert await run_job(run_id) == "failed"


async def test_a_run_is_executed_once_however_many_workers_receive_it(
    session: AsyncSession,
) -> None:
    workspace = await make_workspace(session)
    run_id = await _runnable(session, workspace, job=f"{PATH}.sleep", args="[0.2]")

    outcomes = await asyncio.gather(*(run_job(run_id) for _ in range(5)))

    assert sorted(outcomes) == ["skipped"] * 4 + ["succeeded"]
    assert [call for call, _ in background_jobs.CALLS] == ["sleep"]


async def test_a_run_whose_workspace_was_deleted_is_not_executed(session: AsyncSession) -> None:
    """A workspace_id in a job is a fact about the past, not an authorisation.
    The history goes with the workspace, so there is nothing left to claim."""
    workspace = await make_workspace(session)
    run_id = await _runnable(session, workspace)
    async with session_factory() as own:
        await own.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace})
        await own.commit()

    assert await run_job(run_id) == "skipped"
    assert background_jobs.CALLS == []


async def test_the_request_that_caused_a_job_is_visible_inside_it(session: AsyncSession) -> None:
    """The thread that joins "the user clicked" to "the worker crashed"."""
    workspace = await make_workspace(session)
    run_id = await _runnable(
        session, workspace, job=f"{PATH}.observe_request_id", request_id="01FROMTHEREQUEST"
    )

    await run_job(run_id)

    assert background_jobs.CALLS == [("request_id", "01FROMTHEREQUEST")]


async def test_the_request_id_does_not_leak_into_the_next_job(session: AsyncSession) -> None:
    workspace = await make_workspace(session)
    first = await _runnable(session, workspace, request_id="01FIRST")
    token = set_request_id("01OUTER")
    try:
        await run_job(first)
        assert current_request_id() == "01OUTER"
    finally:
        reset_request_id(token)


async def test_a_long_job_keeps_renewing_its_lease(session: AsyncSession) -> None:
    """Otherwise a job that legitimately takes ten minutes looks exactly like a
    dead worker, and recovery would run it a second time alongside itself."""
    workspace = await make_workspace(session)
    run_id = await _runnable(session, workspace, job=f"{PATH}.sleep", args="[1.3]")
    leases: list[datetime] = []

    async def watch() -> None:
        for _ in range(4):
            await asyncio.sleep(0.3)
            async with session_factory() as own:
                value = (
                    await own.execute(
                        text("SELECT locked_until FROM job_runs WHERE id = :i"), {"i": run_id}
                    )
                ).scalar_one()
            if value is not None:
                leases.append(value)

    watcher = asyncio.create_task(watch())
    outcome = await run_job(run_id, lease_seconds=0.9)
    await watcher

    assert outcome == "succeeded"
    assert len(set(leases)) >= 2, "the lease was never renewed while the job ran"


# ── History: what a customer may see ──────────────────────────────────────
