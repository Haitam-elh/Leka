"""What runs by itself, and when.

LEKA-334. Until now every sweep was run by hand. The schedule is a table, and a
table of dotted job paths is exactly the kind of thing that survives a rename and
then fails at three in the morning, so most of this file is checks that fire the
day someone adds a row — the pattern test_tenant_isolation.py established.

Written before the schedule existed, and run to watch it fail.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import AsyncIterator

import pytest
import redis
from rq.cron import CronJob, CronScheduler
from sqlalchemy import text

from leka.background import JobQueue
from leka.background.schedule import SCHEDULE, TICK_INTERVAL_SECONDS, run_scheduled, schedule_job
from leka.db import session_factory

pytestmark = pytest.mark.integration


def _resolve(dotted_path: str) -> object:
    module_name, _, function = dotted_path.rpartition(".")
    return getattr(importlib.import_module(module_name), function)


@pytest.fixture
async def clean_system_runs() -> AsyncIterator[None]:
    """System runs belong to no workspace, so no fixture cascades them away."""
    yield
    async with session_factory() as session, session.begin():
        await session.execute(text("DELETE FROM job_runs WHERE concurrency_key LIKE 'test:%'"))


# ── The table ─────────────────────────────────────────────────────────────


def test_every_scheduled_job_names_a_real_function() -> None:
    broken = [entry.job for entry in SCHEDULE if not callable(_resolve(entry.job))]
    assert not broken, f"scheduled jobs that do not exist: {broken}"


def test_every_scheduled_job_is_a_plain_synchronous_entry_point() -> None:
    """RQ runs it; the runner calls it in a thread. An `async def` would return a
    coroutine nobody awaits and be recorded as having succeeded."""
    asynchronous = [
        entry.job for entry in SCHEDULE if inspect.iscoroutinefunction(_resolve(entry.job))
    ]
    assert not asynchronous, f"scheduled jobs that are coroutines: {asynchronous}"


def test_the_schedule_covers_every_sweep_that_used_to_be_run_by_hand() -> None:
    """The table cannot silently empty. These are the housekeeping tasks the
    docs used to say to run by hand; each must be here or have a reason not to be."""
    assert {
        "leka.ingestion.tasks.run_sweep",
        "leka.ingestion.tasks.run_reconcile",
        "leka.platform.tasks.run_erase_workspaces_past_grace",
        "leka.identity.tasks.run_purge",
        "leka.background.tasks.run_prune_events",
    } <= {entry.job for entry in SCHEDULE}


def test_names_and_concurrency_keys_are_unique() -> None:
    names = [entry.name for entry in SCHEDULE]
    keys = [entry.key for entry in SCHEDULE]
    assert len(set(names)) == len(names)
    assert len(set(keys)) == len(keys), "two entries sharing a key would block each other"


def test_every_entry_has_exactly_one_way_to_say_when() -> None:
    for entry in SCHEDULE:
        assert (entry.cron is None) != (entry.interval is None), entry.name


def test_every_cron_expression_is_valid() -> None:
    """RQ parses it when the job is built, so an invalid one fails at startup of
    the scheduler rather than never running."""
    for entry in SCHEDULE:
        if entry.cron is not None:
            CronJob(queue_name="leka", func_name=entry.job, cron=entry.cron)


def test_sweeps_go_on_the_low_queue() -> None:
    """A retention sweep can take ten minutes. On any other queue it would make
    the work a person is waiting for wait behind it."""
    assert {entry.queue for entry in SCHEDULE} == {JobQueue.LOW}


# ── The cron configuration ────────────────────────────────────────────────


def test_the_cron_file_registers_the_tick_and_every_scheduled_job() -> None:
    scheduler = CronScheduler(connection=redis.Redis())
    scheduler.load_config_from_file("leka.background.cron_config")

    jobs = {job.name: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"background-maintenance", *(entry.name for entry in SCHEDULE)}

    tick = jobs["background-maintenance"]
    assert tick.func_name == "leka.background.tasks.run_maintenance_tick"
    assert tick.interval == TICK_INTERVAL_SECONDS
    assert tick.queue_name == JobQueue.HIGH.value
    assert tick.job_options["ttl"] > 0, "a backed-up queue must drop stale ticks, not stack them"


def test_scheduled_jobs_are_registered_on_the_high_queue_but_run_on_their_own() -> None:
    """The cron only creates a run and offers it, which is cheap, so it goes on
    the queue that is never behind a sweep. The sweep itself goes where the entry says."""
    scheduler = CronScheduler(connection=redis.Redis())
    scheduler.load_config_from_file("leka.background.cron_config")

    for entry in SCHEDULE:
        job = next(job for job in scheduler.get_jobs() if job.name == entry.name)
        assert job.queue_name == JobQueue.HIGH.value
        assert job.func_name == "leka.background.schedule.run_scheduled"
        assert job.args == (entry.job, entry.key, entry.queue.value)
        assert job.kwargs == ({"job_kwargs": entry.kwargs} if entry.kwargs else {})


def test_the_scheduled_reconciliation_reports_and_does_not_delete_by_default() -> None:
    """Its failure mode is deleting live data. A schedule that started doing that
    on its own would skip the "look at the number first" the docs ask for."""
    (reconcile,) = (e for e in SCHEDULE if e.job == "leka.ingestion.tasks.run_reconcile")
    assert reconcile.kwargs == {"dry_run": True}


# ── Scheduling a run ──────────────────────────────────────────────────────


@pytest.mark.usefixtures("clean_system_runs")
async def test_a_scheduled_sweep_becomes_a_system_run_with_its_key() -> None:
    outcome = await schedule_job("tests.background_jobs.succeed", "test:sweep", JobQueue.LOW.value)

    assert outcome == "scheduled"
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT for_workspace_id, queue, status FROM job_runs "
                    "WHERE concurrency_key = 'test:sweep'"
                )
            )
        ).one()
    assert tuple(row) == (None, "leka:low", "queued")


@pytest.mark.usefixtures("clean_system_runs")
async def test_a_sweep_is_not_started_while_the_last_one_is_still_active() -> None:
    """The retention sweep is bounded per run and picks up where it stopped, so
    two of them at once would only fight over the same rows."""
    first = await schedule_job("tests.background_jobs.succeed", "test:overlap", "leka:low")
    second = await schedule_job("tests.background_jobs.succeed", "test:overlap", "leka:low")

    assert (first, second) == ("scheduled", "already_active")


def test_the_entry_point_rq_calls_is_synchronous() -> None:
    assert not inspect.iscoroutinefunction(run_scheduled)
