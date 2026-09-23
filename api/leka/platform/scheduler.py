"""The scheduler process: puts the tick and the sweeps on the queue on time.

    python -m leka.platform.scheduler

`rq cron leka.background.cron_config`, with the process set up first, for
the reasons given in leka.platform.worker. It enqueues and runs nothing: the
worker runs what it enqueues.

Without it nothing is dispatched. The tick it schedules every ten seconds is
what turns `events` into `job_runs` and offers them to Redis
(docs/background.md), so a deployment with a worker and no scheduler has a
worker that waits for ever.

ONE PER DEPLOYMENT. Two schedulers would each enqueue every tick and every
sweep. The runs are idempotent, so nothing would break, but everything would
be done twice.
"""

from __future__ import annotations

from rq.cron import CronScheduler

from leka.background import worker_connection
from leka.core.config import settings
from leka.core.logging import configure_logging
from leka.platform.monitoring import configure_monitoring

# A dotted path, as `rq cron` takes it: loading the module is what registers
# the schedule, so the scheduler imports it rather than this file.
CRON_CONFIG = "leka.background.cron_config"


def main() -> None:
    configure_logging(settings)
    configure_monitoring(settings)

    scheduler = CronScheduler(connection=worker_connection())
    scheduler.load_config_from_file(CRON_CONFIG)
    # RQ leaves this one method unannotated; it runs until SIGTERM.
    scheduler.start()  # type: ignore[no-untyped-call]


if __name__ == "__main__":  # pragma: no cover - the process itself
    main()
