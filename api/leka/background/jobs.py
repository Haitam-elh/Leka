"""The background queue: work that must happen, but not inside a request.

LEKA's architecture splits two loops. The interactive loop answers a question
from context that is already prepared. The background loop does the expensive
things — syncing, normalising, and the housekeeping in this file. A request
that deletes a customer must not wait while half a million objects are
removed from a bucket.

WHAT THIS IS NOT. It is not a scheduler and it is not a retry framework. RQ
gives us a durable list in Redis and a worker that drains it; that is the
whole of it. Anything needing "every hour" is driven from outside, by cron or
by `rq worker` plus a timer, and every task in LEKA is written so that
running it twice is the same as running it once.

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
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from leka.core.config import settings

logger = structlog.get_logger(__name__)

# One queue. LEKA is one worker's worth of work for a long time yet, and
# several queues with one worker between them is a way to starve one of them
# by accident. Splitting is a decision to take when a slow job is measurably
# delaying a fast one.
QUEUE_NAME = "leka"

_queue: Any | None = None


def queue() -> Any:
    """The RQ queue for this process, created on first use.

    Not at import: a module import must not open a network connection, or
    every test and every migration pays for one it never uses.
    """
    global _queue
    if _queue is None:
        import redis
        from rq import Queue

        _queue = Queue(
            QUEUE_NAME,
            connection=redis.from_url(
                str(settings.redis_url), socket_connect_timeout=2, socket_timeout=2
            ),
        )
    return _queue


def reset_queue() -> None:
    """Forget the built queue. For tests that substitute one."""
    global _queue
    _queue = None


async def enqueue(job: str, *args: Any, **kwargs: Any) -> bool:
    """Put a job on the queue. Says whether it got there.

    `job` is a dotted path — "leka.ingestion.tasks.run_sweep" — because that
    is what RQ stores anyway, and because naming it avoids an import that
    would point the wrong way through the module layers.

    Returns False rather than raising when the queue is unreachable. Callers
    are doing something else that matters; see the module docstring for why
    this is safe here and would not be safe everywhere.

    The Redis call is synchronous, so it runs in a worker thread. It is a
    handful of milliseconds, but a handful of milliseconds inside the event
    loop is still every other request waiting.
    """
    try:
        await asyncio.to_thread(lambda: queue().enqueue(job, *args, **kwargs))
    except Exception as error:
        logger.error("job_not_enqueued", job=job, error=str(error))
        return False
    logger.info("job_enqueued", job=job)
    return True


__all__ = ["QUEUE_NAME", "enqueue", "queue", "reset_queue"]
