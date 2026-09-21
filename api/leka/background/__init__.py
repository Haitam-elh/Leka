"""The background loop's machinery: events, and what drives them.

The interactive loop answers from prepared context; this is what prepares it.
Events say something happened; the guarantees around them let a queue lose a
message or a dispatcher run twice without anything happening twice.

Depends on leka.core and leka.db only, and sits BELOW leka.platform on purpose:
platform enqueues work itself (erasing a workspace purges its objects), so it
must be able to import this. The price is that this cannot import platform —
event payloads and job arguments are JSON, never a typed workspace.

See docs/adr/012-events-and-job-runs.md.
"""

from leka.background.jobs import QUEUE_NAME, enqueue, queue, reset_queue
from leka.background.models import Event, EventStatus

__all__ = ["QUEUE_NAME", "Event", "EventStatus", "enqueue", "queue", "reset_queue"]
