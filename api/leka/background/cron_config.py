"""The configuration `rq cron` loads.

    python -m leka.platform.scheduler

which is `rq cron leka.background.cron_config` with logging and Sentry set up
first (see leka/platform/scheduler.py).

One process, run alongside the worker. It puts jobs on the queue at the right
times and does nothing else; the worker runs them. If it is not running nothing
breaks — work already published still flows, the sweeps just stop being scheduled,
which is the state of the world before LEKA-334.

The table itself is in leka.background.schedule, so it can be tested without
starting a scheduler.
"""

from __future__ import annotations

from rq import cron

from leka.background.models import JobQueue
from leka.background.schedule import SCHEDULE, TICK_INTERVAL_SECONDS, run_scheduled
from leka.background.tasks import run_maintenance_tick

# The tick expires if the queue is so backed up that it has not started within
# three intervals. A tick is idempotent and the next one is coming, so a stale
# one is worth nothing — and without this a stalled worker would come back to a
# queue full of them.
cron.register(
    run_maintenance_tick,
    JobQueue.HIGH.value,
    interval=TICK_INTERVAL_SECONDS,
    ttl=TICK_INTERVAL_SECONDS * 3,
    name="background-maintenance",
)

for entry in SCHEDULE:
    cron.register(
        run_scheduled,
        JobQueue.HIGH.value,
        args=(entry.job, entry.key, entry.queue.value),
        kwargs={"job_kwargs": entry.kwargs} if entry.kwargs else None,
        cron=entry.cron,
        interval=entry.interval,
        name=entry.name,
    )
