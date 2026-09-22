"""Running one job run, on a worker.

The RQ entry point is `execute(run_id)`. RQ delivers a message at least once, so
everything here starts from "someone else may be doing this too" and settles it
with a single UPDATE (`JobRunRepository.claim`), not with a check.

    claim            queued -> running, for exactly one worker
    run the job      in a thread, while a heartbeat renews the lease
    record           succeeded, or retrying/failed with the error kept

THE JOB IS RUN IN A THREAD. The existing tasks are synchronous RQ entry points
that call `asyncio.run` themselves (leka.ingestion.tasks.run_sweep), and
`asyncio.run` cannot be called from inside a running loop. A thread gives the
job a loop of its own and leaves this one free to keep the lease alive — which is
what stops a job that legitimately takes ten minutes from looking exactly like a
dead worker.

THE BOOKKEEPING USES ITS OWN ENGINE, WITHOUT A POOL. An asyncpg connection
belongs to the loop that opened it. The job's loop and this one would otherwise
share leka.db's pool, and one would be handed a connection the other opened. A
few statements per run do not need pooling; they need to be correct.

A job receives the arguments stored on its run, and finds the request that caused
it on `current_request_id()` and in every log line — so "the user clicked" and
"the worker crashed three minutes later" are one search.
"""

from __future__ import annotations

import asyncio
import importlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from leka.background.repository import JobRunRepository
from leka.core.config import settings
from leka.core.request_context import reset_request_id, set_request_id

logger = structlog.get_logger(__name__)

Outcome = Literal["succeeded", "retrying", "failed", "skipped", "lost"]

# How long RQ lets a job run before killing its work-horse. Generous, because the
# lease is what decides whether a worker is alive; this only bounds a job stuck
# in a loop. A job killed here is recovered like any dead worker.
RQ_JOB_TIMEOUT = 7200


def _resolve(dotted_path: str) -> Callable[..., Any]:
    """The function a job path names. Raises if it does not name one.

    An import error, a missing attribute and a non-callable are all the same
    thing to the caller: this job will not run next time either.
    """
    module_name, _, function = dotted_path.rpartition(".")
    module = importlib.import_module(module_name)
    target = getattr(module, function)
    if not callable(target):
        msg = f"{dotted_path} is not callable"
        raise TypeError(msg)
    target_callable: Callable[..., Any] = target
    return target_callable


async def _renew_lease(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    lease_seconds: float,
    stop: asyncio.Event,
) -> None:
    """Keep the lease alive until told to stop, or until it is lost.

    Renews at a third of the lease, so it survives two missed beats before
    recovery would call the worker dead.
    """
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=lease_seconds / 3)
            return
        except TimeoutError:
            pass
        async with factory() as session:
            alive = await JobRunRepository(session).heartbeat(
                run_id, now=datetime.now(UTC), lease_seconds=lease_seconds
            )
            await session.commit()
        if not alive:
            logger.warning("run_lease_lost", run_id=str(run_id))
            return


async def run_job(run_id: uuid.UUID, *, lease_seconds: float | None = None) -> Outcome:
    """Claim a run, execute its job, record how it went.

    Returns what happened, for tests and logs: `skipped` means another worker had
    it, or it no longer exists (a workspace deleted after the job was enqueued —
    the history went with it, so there is nothing to claim). `lost` means the
    lease expired while the job ran and recovery took the run over; this worker
    then leaves the record alone.
    """
    lease = lease_seconds or float(settings.job_lease_seconds)
    engine = create_async_engine(str(settings.database_url), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        return await _run(run_id, lease, factory)
    finally:
        await engine.dispose()


async def _run(
    run_id: uuid.UUID, lease: float, factory: async_sessionmaker[AsyncSession]
) -> Outcome:
    async with factory() as session:
        run = await JobRunRepository(session).claim(
            run_id, now=datetime.now(UTC), lease_seconds=lease
        )
        await session.commit()
    if run is None:
        logger.info("run_skipped", run_id=str(run_id))
        return "skipped"

    job, args, kwargs = run.job, list(run.args), dict(run.kwargs)
    token = set_request_id(run.request_id) if run.request_id else None
    structlog.contextvars.bind_contextvars(
        run_id=str(run.id), job=job, attempt=run.attempts, request_id=run.request_id
    )
    try:
        return await _execute(run_id, job, args, kwargs, lease, factory)
    finally:
        structlog.contextvars.unbind_contextvars("run_id", "job", "attempt", "request_id")
        if token is not None:
            reset_request_id(token)


async def _execute(
    run_id: uuid.UUID,
    job: str,
    args: list[object],
    kwargs: dict[str, object],
    lease: float,
    factory: async_sessionmaker[AsyncSession],
) -> Outcome:
    try:
        target = _resolve(job)
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        return await _record_failure(
            run_id, f"cannot resolve job {job!r}: {error}", factory, permanent=True
        )

    stop = asyncio.Event()
    renewal = asyncio.create_task(_renew_lease(factory, run_id, lease, stop))
    error_text: str | None = None
    try:
        await asyncio.to_thread(target, *args, **kwargs)
    except Exception as error:
        error_text = f"{type(error).__name__}: {error}"
        logger.error("job_failed", error=error_text, exc_info=True)
    finally:
        stop.set()
        await renewal

    if error_text is not None:
        return await _record_failure(run_id, error_text, factory)

    async with factory() as session:
        recorded = await JobRunRepository(session).succeed(run_id, now=datetime.now(UTC))
        await session.commit()
    if not recorded:
        logger.warning("run_finished_after_lease_lost", run_id=str(run_id))
        return "lost"
    logger.info("job_succeeded")
    return "succeeded"


async def _record_failure(
    run_id: uuid.UUID,
    error: str,
    factory: async_sessionmaker[AsyncSession],
    *,
    permanent: bool = False,
) -> Outcome:
    async with factory() as session:
        updated = await JobRunRepository(session).fail_attempt(
            run_id,
            error,
            now=datetime.now(UTC),
            retry_base_seconds=settings.job_retry_base_seconds,
            retry_max_seconds=settings.job_retry_max_seconds,
            permanent=permanent,
        )
        await session.commit()
    if updated is None:
        return "lost"
    outcome: Outcome = "failed" if updated.status.value == "failed" else "retrying"
    logger.warning("job_attempt_failed", outcome=outcome, attempts=updated.attempts)
    return outcome


def execute(run_id: str) -> Outcome:
    """Entry point for RQ, which is synchronous. `run_id` is a string because RQ
    serialises arguments to JSON and a UUID is not one."""
    return asyncio.run(run_job(uuid.UUID(run_id)))
