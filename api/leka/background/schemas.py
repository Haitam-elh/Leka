"""Types crossing the boundary of the background module.

JobRunRead is what a customer may be told about one run of their own, and NOTHING else. The
fields it leaves out are left out on purpose:

    last_error         an exception message names hosts, paths and queries. The API says
                       elsewhere (a 500) that it will not do that, and this is the same rule
    args, kwargs       how the system talks to itself; they may carry identifiers
    concurrency_key    an internal name
    event_id, enqueued_at, locked_until
                       plumbing between the passes, which no customer can act on

It is built from the row, so a column added to JobRun later is NOT exposed by accident: it
has to be added here, on purpose, and a test holds the list.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from leka.background.models import JobQueue, JobStatus


class JobRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job: str = Field(description="What ran, as the system names it.")
    status: JobStatus = Field(
        description=(
            "queued: waiting for a worker. running: a worker has it. retrying: an attempt failed "
            "and another is due at next_run_at. succeeded and failed are final."
        )
    )
    queue: JobQueue = Field(description="How urgent it was: leka:high, leka or leka:low.")
    attempts: int = Field(description="How many times a worker has started it.")
    max_attempts: int = Field(description="After this many attempts a failure is final.")
    created_at: datetime
    started_at: datetime | None = Field(description="When a worker first started it.")
    finished_at: datetime | None = Field(description="When it reached a final status.")
    next_run_at: datetime | None = Field(description="When a retry is due. Null unless retrying.")
    request_id: str | None = Field(
        description="The request that caused it, if there was one. Quote it when you write to us."
    )
