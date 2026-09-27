"""What runs by itself, and when.

A table, like the event routes: each row is a job that used to be run by hand,
named by dotted path, with when to run it and which queue it goes on. Adding a
scheduled task is one row here; `tests/test_background_schedule.py` checks every
row names a function that exists, is synchronous, and has a valid schedule the day
it is added.

THE SCHEDULER ONLY SCHEDULES. `rq cron` (see cron_config.py) does not run these
tasks; it puts `run_scheduled` on the queue, which creates a job RUN — visible in
the history, and refused if the previous one is still active — and offers that
run to the queue named here. So a sweep that takes ten minutes shows up as a
system run with its attempts and its error like any other job, and cannot overlap
itself.

The scheduling call goes on `leka:high` because it is cheap and must never wait
behind the sweep it is scheduling. The sweep goes where its row says.

THE TASKS ARE NOT RE-WRITTEN. Retention, erasure, session purge and reconciliation
are tested and their order is deliberate (docs/data-lifecycle.md); this only
decides when they run. Every one is safe to run twice, which is what lets a
schedule that fires while the last run is still going simply be refused.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from leka.background.models import JobQueue
from leka.background.service import enqueue_job
from leka.core.config import settings

# How often the maintenance tick runs: dispatch events, repair broken runs, offer
# waiting ones to Redis. Cheap when idle, so short; it sets the floor on how soon
# a published event starts.
TICK_INTERVAL_SECONDS = 10


@dataclass(frozen=True)
class Scheduled:
    name: str
    job: str
    cron: str | None = None
    interval: int | None = None
    queue: JobQueue = JobQueue.LOW
    kwargs: dict[str, object] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """The concurrency key: one active run of this sweep at a time."""
        return f"schedule:{self.name}"


# Minutes are staggered so the sweeps do not all start at the top of the hour and
# contend for the same connections.
SCHEDULE: tuple[Scheduled, ...] = (
    Scheduled("retention-sweep", "leka.ingestion.tasks.run_sweep", cron="0 * * * *"),
    Scheduled(
        "erase-workspaces",
        "leka.platform.tasks.run_erase_workspaces_past_grace",
        cron="15 * * * *",
    ),
    Scheduled("purge-sessions", "leka.identity.tasks.run_purge", cron="30 * * * *"),
    # Weekly, and dry unless LEKA_RECONCILE_DELETES says otherwise: its failure
    # mode is deleting live data (docs/data-lifecycle.md).
    Scheduled(
        "reconcile-orphans",
        "leka.ingestion.tasks.run_reconcile",
        cron="0 3 * * 0",
        kwargs={"dry_run": not settings.reconcile_deletes},
    ),
    Scheduled("prune-events", "leka.background.tasks.run_prune_events", cron="30 3 * * *"),
    # Processed data (LEKA-360): runs a dead worker left, history past 90
    # days, what deleted records gave to sources no longer extracted.
    Scheduled(
        "processing-sweep", "leka.ingestion.lifecycle.run_processing_sweep", cron="45 3 * * *"
    ),
    # Every activated source, a light call each (LEKA-344). Off the hour's
    # busy minutes, like the rest.
    Scheduled(
        "source-health", "leka.connectors.health.run_health_checks", cron="5,20,35,50 * * * *"
    ),
    # Offers a pass to every switched-on source not tried for an hour
    # (LEKA-352). The passes themselves run on the default queue, one per
    # source at a time.
    Scheduled(
        "source-sync", "leka.ingestion.sync.run_enqueue_due_syncs", cron="10,25,40,55 * * * *"
    ),
)


async def schedule_job(
    job: str, concurrency_key: str, queue: str, job_kwargs: dict[str, object] | None = None
) -> Literal["scheduled", "already_active"]:
    """Create a system run of `job` and offer it to `queue`.

    `already_active` means the previous run of this sweep has not finished, which
    is not an error: the sweep is bounded per run and picks up where it stopped, so
    two at once would only fight over the same rows.
    """
    run = await enqueue_job(
        job,
        job_kwargs=job_kwargs,
        queue=JobQueue(queue),
        concurrency_key=concurrency_key,
    )
    return "scheduled" if run is not None else "already_active"


def run_scheduled(
    job: str, concurrency_key: str, queue: str, job_kwargs: dict[str, object] | None = None
) -> str:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(schedule_job(job, concurrency_key, queue, job_kwargs))
