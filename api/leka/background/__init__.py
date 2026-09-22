"""The background loop's machinery: events, and what drives them.

The interactive loop answers from prepared context; this is what prepares it.
Events say something happened, job runs record the work done about it, and the
guarantees between them let a queue lose a message, a worker die or a dispatcher
run twice without anything happening twice.

Depends on leka.core and leka.db only, and sits BELOW leka.platform on purpose:
platform enqueues work itself (erasing a workspace purges its objects), so it
must be able to import this. The price is that this cannot import platform —
event payloads and job arguments are JSON, never a typed workspace.

See docs/adr/012-events-and-job-runs.md.
"""

from leka.background.jobs import QUEUE_NAME, enqueue, queue, reset_queue
from leka.background.models import (
    ACTIVE_JOB_STATUSES,
    FINAL_STATUSES,
    TRANSITIONS,
    Event,
    EventStatus,
    JobQueue,
    JobRun,
    JobStatus,
)
from leka.background.service import enqueue_job, publish_event

__all__ = [
    "ACTIVE_JOB_STATUSES",
    "FINAL_STATUSES",
    "QUEUE_NAME",
    "TRANSITIONS",
    "Event",
    "EventStatus",
    "JobQueue",
    "JobRun",
    "JobStatus",
    "enqueue",
    "enqueue_job",
    "publish_event",
    "queue",
    "reset_queue",
]
