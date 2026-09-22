"""The background loop's own settings: events, job runs, the queue, retry and lease.

Fields arrive here as the deliverable that needs them is built (LEKA-334); see
docs/adr/012-events-and-job-runs.md. Every one is bounded: a 0 reads as "disabled"
to whoever types it and as "never try" to the code, so it is refused rather than
given a meaning.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator


class BackgroundSettings:
    """Dispatch, retry, lease and retention knobs for leka.background."""

    # How many pending events one dispatcher pass turns into runs, and how many
    # runs one enqueue pass offers to Redis. Bounded, because each pass holds a
    # row lock for every row it handles.
    dispatch_batch_size: int = Field(default=100, ge=1, le=1000)
    # How often dispatching an event may fail before it is given up on.
    # ge=1: a 0 reads as "disabled" to whoever types it and as "never try" to
    # the code, so it is refused rather than given a meaning.
    dispatch_max_attempts: int = Field(default=5, ge=1, le=50)

    # How many times a job run is attempted before it is failed for good. ge=1,
    # for the same reason as above.
    job_max_attempts: int = Field(default=3, ge=1, le=20)
    # The delay before a retry doubles each attempt — base, 2x, 4x ... — up to
    # the cap. Not a fixed interval: a downstream that is down for a minute
    # should not be hammered every thirty seconds.
    job_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    job_retry_max_seconds: int = Field(default=3600, ge=1, le=86400)
    # How long a worker may go without renewing its lease before the run is
    # taken to be lost. It renews at a third of this, so it survives two missed
    # beats. Long enough to ride out a slow database, short enough that a dead
    # worker does not hold a concurrency key for an hour.
    job_lease_seconds: int = Field(default=300, ge=30, le=7200)
    # How long a run may sit "queued" after Redis accepted it before it is offered
    # again. It is the net under a Redis that lost its memory; the claim makes a
    # duplicate message harmless, so this errs long rather than short.
    job_stale_enqueued_seconds: int = Field(default=3600, ge=60, le=86400)

    @model_validator(mode="after")
    def _retry_cap_is_not_below_its_base(self) -> Self:
        """A cap under the base delay would make every retry wait less than the
        first one was meant to, and the backoff quietly stop being one."""
        if self.job_retry_max_seconds < self.job_retry_base_seconds:
            msg = (
                f"LEKA_JOB_RETRY_MAX_SECONDS ({self.job_retry_max_seconds}) is below "
                f"LEKA_JOB_RETRY_BASE_SECONDS ({self.job_retry_base_seconds})"
            )
            raise ValueError(msg)
        return self


__all__ = ["BackgroundSettings"]
