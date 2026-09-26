"""Background work for the background module: the passes that keep the loop moving.

Four, and each is a plain function with a synchronous entry point, safe to run
twice and concurrently — the house pattern, and what lets one tick drive them all.

    dispatch_pending_events   event -> job runs (database writes only)
    recover_runs              lost workers, due retries, runs the queue forgot
    enqueue_pending_runs      job runs -> Redis. The ONLY thing that talks to it
    prune_events              the outbox does not grow for ever

REDIS IS NEVER ON THE PATH OF A TRANSACTION. The dispatcher writes rows and
commits; a separate pass offers those rows to the queue. That is the reason for
the split. Talking to Redis while holding row locks meant a Redis timeout was a
lock held for two seconds per event, and a worker could pick a message up before
the transaction that created its run had committed. Now a run is durable before
anyone hears of it, and "the queue was down" is a row saying `enqueued_at IS NULL`.

Run by hand, or by whatever drives the background loop:

    python -m leka.background.tasks
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog

from leka.background.jobs import enqueue
from leka.background.repository import EventDispatchRepository, JobRunRepository
from leka.background.routes import ROUTES
from leka.background.runner import RQ_JOB_TIMEOUT
from leka.core.config import settings
from leka.db import load_schema, session_factory, system_scope

logger = structlog.get_logger(__name__)

# The RQ function every run goes through. A string, like every job.
EXECUTE = "leka.background.runner.execute"


async def dispatch_pending_events(
    *, batch: int | None = None, max_attempts: int | None = None
) -> dict[str, int]:
    """Turn pending events into job runs. Safe to run twice, and concurrently.

    system_scope because it sweeps every workspace — exactly what that exists
    for, declared in one line a reviewer can see.

    Database writes only: the runs are created, the event is marked `runs_created`,
    and that commits. Putting the runs on the queue is another pass. If the
    dispatcher dies between creating the runs and marking the event, the next
    pass creates them again and the unique (event, job) refuses it — which is
    what turns "at-least-once" into "one run".

    An event that fails to dispatch — a bug, a constraint — is retried and, after
    `dispatch_max_attempts`, marked failed, so one poisoned event cannot hold up
    the ones behind it for ever. Each event is handled inside a savepoint for the
    same reason: its failure must not take the rest of the batch with it.
    """
    limit = batch or settings.dispatch_batch_size
    give_up_after = max_attempts or settings.dispatch_max_attempts
    result = {"runs_created": 0, "failed": 0, "unrouted": 0, "retry_later": 0}

    with system_scope():
        async with session_factory() as session:
            events = EventDispatchRepository(session)
            runs = JobRunRepository(session)
            for event in await events.claim_pending(limit=limit):
                routes = ROUTES.get(event.type, ())
                if not routes:
                    events.mark_unroutable(event, f"no route for event type {event.type!r}")
                    result["unrouted"] += 1
                    logger.error("event_unroutable", event_id=str(event.id), type=event.type)
                    continue

                # Read before the savepoint: a rollback expires the object, and
                # touching an expired attribute in async code is a lazy load.
                attempts_so_far = event.dispatch_attempts
                try:
                    async with session.begin_nested():
                        for route in routes:
                            await runs.create(
                                job=route.job,
                                args=[str(event.id)],
                                event_id=event.id,
                                for_workspace_id=event.workspace_id,
                                request_id=event.request_id,
                                queue=route.queue,
                            )
                        events.mark_runs_created(event, at=datetime.now(UTC))
                except Exception as error:
                    give_up = attempts_so_far + 1 >= give_up_after
                    event.dispatch_attempts = attempts_so_far + 1
                    event.last_error = f"{type(error).__name__}: {error}"[:1000]
                    if give_up:
                        events.mark_unroutable(event, event.last_error)
                    result["failed" if give_up else "retry_later"] += 1
                    logger.error("event_dispatch_failed", event_id=str(event.id), exc_info=True)
                    continue
                result["runs_created"] += 1

            await session.commit()

    logger.info("event_dispatch_completed", **result)
    return result


async def enqueue_pending_runs(
    *, batch: int | None = None, only: Sequence[uuid.UUID] | None = None
) -> dict[str, int]:
    """Offer runs the queue has not been told about, and remember that it was.

    The run is locked (SKIP LOCKED) while it is offered, then stamped. A crash
    between the two offers it twice, which is harmless: `claim` lets one worker
    act on it. The other order would lose it.

    If the first offer fails Redis is down, and the rest would only fail the same
    way, each after a connection timeout with a lock held. So the pass stops there
    and leaves the others exactly as they were: unenqueued, and found again next
    pass. Nothing is lost because Redis had a bad minute.
    """
    limit = batch or settings.dispatch_batch_size
    result = {"enqueued": 0, "queue_down": 0}

    async with session_factory() as session:
        repository = JobRunRepository(session)
        for run in await repository.claim_unenqueued(limit=limit, only=only):
            offered = await enqueue(
                EXECUTE,
                str(run.id),
                queue_name=run.queue.value,
                job_timeout=RQ_JOB_TIMEOUT,
            )
            if not offered:
                result["queue_down"] = 1
                break
            repository.mark_enqueued(run, at=datetime.now(UTC))
            result["enqueued"] += 1
        await session.commit()

    if result["enqueued"] or result["queue_down"]:
        logger.info("run_enqueue_completed", **result)
    return result


async def recover_runs(*, now: datetime | None = None) -> dict[str, int]:
    """Repair what the normal path cannot: a dead worker, a due retry, a lost message.

    None of these can be done by the thing that went wrong. A worker that died
    cannot report it; a retry waiting in the database has nobody to wake it; a run
    Redis forgot does not know it was forgotten. So a pass looks for each.

    Order matters: leases first, so a run recovered as `retrying` is considered
    for promotion in the same pass (its delay has not elapsed, so it will wait).
    """
    moment = now or datetime.now(UTC)
    batch = settings.dispatch_batch_size
    retry = {
        "retry_base_seconds": settings.job_retry_base_seconds,
        "retry_max_seconds": settings.job_retry_max_seconds,
    }

    async with session_factory() as session:
        repository = JobRunRepository(session)
        result = {
            "leases_expired": await repository.expire_leases(now=moment, limit=batch, **retry),
            "retries_promoted": await repository.promote_due_retries(now=moment, limit=batch),
            "enqueues_forgotten": await repository.forget_stale_enqueues(
                older_than=moment - timedelta(seconds=settings.job_stale_enqueued_seconds),
                limit=batch,
            ),
        }
        await session.commit()

    if any(result.values()):
        logger.info("run_recovery_completed", **result)
    return result


async def run_maintenance() -> dict[str, dict[str, int]]:
    """One tick of the background loop: everything that moves work along.

    Cheap when there is nothing to do, so it can run every few seconds. The order
    is the dataflow: events become runs, broken runs are repaired, then whatever
    is waiting goes to Redis.
    """
    return {
        "events": await dispatch_pending_events(),
        "recovery": await recover_runs(),
        "queue": await enqueue_pending_runs(),
    }


async def prune_events(
    *, now: datetime | None = None, batch: int = 1000, max_batches: int = 20
) -> int:
    """Delete settled events (runs created, or failed) older than the retention.

    Bounded, like the payload sweep: a first run after the retention changes can
    match a great many rows, and a task that tries to finish in one go is one
    that is killed halfway. It stops after max_batches and the next run picks up
    where this one left off.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=settings.event_retention_days)
    removed = 0

    for _ in range(max_batches):
        with system_scope():
            async with session_factory() as session:
                deleted = await EventDispatchRepository(session).delete_settled_before(
                    cutoff, limit=batch
                )
                await session.commit()
        removed += deleted
        if deleted < batch:
            break

    logger.info("event_prune_completed", removed=removed)
    return removed


def run_dispatch() -> dict[str, int]:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(dispatch_pending_events())


def run_maintenance_tick() -> dict[str, dict[str, int]]:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(run_maintenance())


def run_prune_events() -> int:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(prune_events())


async def _by_hand() -> None:
    """Both passes in ONE loop: the connection pool belongs to the loop that
    opened it, and a second asyncio.run() inherits connections of a closed one."""
    await run_maintenance()
    await prune_events()


if __name__ == "__main__":  # pragma: no cover
    load_schema()  # every table, as the API has (leka/schema.py)
    asyncio.run(_by_hand())
