"""The background queue: work that must happen, but not inside a request.

LEKA's architecture splits two loops. The interactive loop answers a question
from context that is already prepared. The background loop does the expensive
things — syncing, normalising, and the housekeeping in this file. A request
that deletes a customer must not wait while half a million objects are
removed from a bucket.

WHAT THIS IS. The transport: RQ gives us a durable list in Redis and a worker
that drains it, and this puts a job on it. It knows nothing about retries or
schedules. Those live beside it — runner.py (state, attempts, leases),
schedule.py and cron_config.py (what runs every hour) — and are described in
docs/background.md. Every task in LEKA is written so that running it twice is the
same as running it once, which is what lets all of that be at-least-once.

JOBS ARE NAMED BY STRING, never imported. `enqueue("leka.ingestion.tasks.x")`
rather than importing x and passing the function. Two reasons, and the second
is the real one: RQ serialises a function reference as its dotted path
anyway, and leka.background sits BELOW every module that owns a job in the
dependency order (architecture rule 1), so importing the task here would
invert the one rule the module layout exists to enforce.

THIS LIVED IN leka.platform UNTIL LEKA-334. It moved down to leka.background,
below platform, so that the events and the execution history built there and
the queue they hand work to are one mechanism rather than two — and so that
platform, which enqueues a purge when a workspace is erased, can still import
it. Nothing about how it behaves changed.

FAILING TO ENQUEUE IS NOT SILENT, AND NOT FATAL. If Redis is unreachable the
attempt is logged as an error and the caller carries on. That is deliberate:
the work this queue carries is housekeeping with a safety net behind it — the
reconciliation sweep finds objects no row speaks for, whatever the reason
nobody deleted them. Refusing to delete a customer's account because a queue
was briefly down would be the worse failure.

WORK THAT HAS NO SUCH NET GOES THROUGH A JOB RUN INSTEAD. leka.background's
`enqueue_job` writes the run to the database first and this second, so a queue
that refuses the message leaves a row saying "never enqueued" that the next pass
picks up. Nothing is lost because Redis had a bad minute. This function is the
transport under both, and stays fail-soft on its own.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from leka.core.config import settings

logger = structlog.get_logger(__name__)

# The default queue. There are three (JobQueue): leka:high for work a person is
# waiting for, this one, and leka:low for the sweeps, drained in that order by a
# single worker. That is the only priority RQ has, and it has two limits worth
# knowing: a continuous stream of high starves low, and a long job blocks
# everything whatever its queue — priority only chooses the NEXT job. See ADR 013.
QUEUE_NAME = "leka"

_queue: Any | None = None
# The other queues (leka:high, leka:low), built on first use like the default.
# The default keeps its own slot: it is what most callers use, and what tests
# replace to see what would have been enqueued.
_named_queues: dict[str, Any] = {}


def _build(name: str) -> Any:
    import redis
    from rq import Queue

    return Queue(
        name,
        connection=redis.from_url(
            str(settings.redis_url), socket_connect_timeout=2, socket_timeout=2
        ),
    )


def queue(name: str = QUEUE_NAME) -> Any:
    """The RQ queue of that name for this process, created on first use.

    Not at import: a module import must not open a network connection, or
    every test and every migration pays for one it never uses.
    """
    global _queue
    if name == QUEUE_NAME:
        if _queue is None:
            _queue = _build(name)
        return _queue
    if name not in _named_queues:
        _named_queues[name] = _build(name)
    return _named_queues[name]


def reset_queue() -> None:
    """Forget every built queue. For tests that substitute one."""
    global _queue
    _queue = None
    _named_queues.clear()


async def enqueue(job: str, *args: Any, queue_name: str = QUEUE_NAME, **kwargs: Any) -> bool:
    """Put a job on a queue. Says whether it got there.

    `job` is a dotted path — "leka.ingestion.tasks.run_sweep" — because that
    is what RQ stores anyway, and because naming it avoids an import that
    would point the wrong way through the module layers.

    `queue_name` says which queue; everything else in kwargs is RQ's own
    (`job_timeout`, ...) or the job's.

    Returns False rather than raising when the queue is unreachable. Callers
    are doing something else that matters; see the module docstring for why
    this is safe here and would not be safe everywhere.

    The Redis call is synchronous, so it runs in a worker thread. It is a
    handful of milliseconds, but a handful of milliseconds inside the event
    loop is still every other request waiting.
    """
    try:
        await asyncio.to_thread(lambda: queue(queue_name).enqueue(job, *args, **kwargs))
    except Exception as error:
        logger.error("job_not_enqueued", job=job, queue=queue_name, error=str(error))
        return False
    logger.info("job_enqueued", job=job, queue=queue_name)
    return True


__all__ = ["QUEUE_NAME", "enqueue", "queue", "reset_queue"]
