"""Which attempt the job running here is on (2026-11-01).

1 the first time; more when its worker died mid-job and recovery gave the
job back (its lease expired). A job that keeps its own state — an agent's
run, said « running » by the attempt that died — takes it back only then.
"""

from __future__ import annotations

from contextvars import ContextVar

ATTEMPT: ContextVar[int] = ContextVar("job_attempt", default=0)


def job_attempt() -> int:
    """The attempt of the job this code runs in — 0 outside a job."""
    return ATTEMPT.get()


__all__ = ["ATTEMPT", "job_attempt"]
