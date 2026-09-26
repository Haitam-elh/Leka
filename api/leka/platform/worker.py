"""The worker process: runs what the background loop puts on the queue.

    python -m leka.platform.worker               # leka:high, leka, leka:low
    python -m leka.platform.worker leka:high     # a second worker, high only

Rather than `rq worker`, because a process that runs our code must be set up
the way the API is before it runs any. `rq worker` starts RQ and nothing
else, and started that way the worker:

- wrote its log lines without the secret masker of LEKA-335 — a guarantee
  the API kept and the worker silently did not;
- ignored LEKA_LOG_FORMAT, printing coloured console output to a staging log
  collector that expects JSON;
- never initialised Sentry, so an exception in a job reached nobody.
- and never registered the whole schema: a job importing one module met a
  foreign key to a table it had never been shown (leka/schema.py).

Same queues, same order as before: leka:high, leka, leka:low. See JobQueue.

It lives in platform rather than background because it needs
`configure_monitoring`, and background sits below platform and cannot import
it (tests/test_module_boundaries.py).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from rq import Queue, Worker

from leka.background import JobQueue, worker_connection
from leka.core.config import settings
from leka.core.logging import configure_logging
from leka.db import load_schema
from leka.platform.monitoring import configure_monitoring

# Drained in this order, which is the only priority RQ has.
QUEUES: tuple[JobQueue, ...] = (JobQueue.HIGH, JobQueue.DEFAULT, JobQueue.LOW)


def queues_to_drain(names: Sequence[str]) -> tuple[JobQueue, ...]:
    """The queues named on the command line, or all three.

    Named ones must exist: a worker listening on a misspelt queue drains
    nothing and says nothing, which is worse than refusing to start.
    """
    if not names:
        return QUEUES
    return tuple(JobQueue(name) for name in names)


def main(argv: Sequence[str] = ()) -> None:
    queues = queues_to_drain(argv)

    configure_logging(settings)
    # After logging, never before — the same order as the API's lifespan:
    # Sentry scrubs its events with the masker configure_logging builds.
    configure_monitoring(settings)
    # Every table, before RQ forks a work-horse per job: they inherit it.
    load_schema()

    connection = worker_connection()
    worker = Worker(
        [Queue(name.value, connection=connection) for name in queues], connection=connection
    )
    worker.work()


if __name__ == "__main__":  # pragma: no cover - the process itself
    main(sys.argv[1:])
