"""The background loop's own settings: events, job runs, the queue, retry and lease.

Fields arrive here as the deliverable that needs them is built (LEKA-334); see
docs/adr/012-events-and-job-runs.md. Every one is bounded: a 0 reads as "disabled"
to whoever types it and as "never try" to the code, so it is refused rather than
given a meaning.
"""

from __future__ import annotations

from pydantic import Field


class BackgroundSettings:
    """Dispatch, retry, lease and retention knobs for leka.background."""

    # How many times a job run is attempted before it is failed for good. ge=1,
    # for the same reason as above.
    job_max_attempts: int = Field(default=3, ge=1, le=20)


__all__ = ["BackgroundSettings"]
