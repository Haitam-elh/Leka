"""Every database query of the background module.

Three repositories, because these tables are read very different ways.

EventRepository is the ordinary one: it belongs to ONE workspace, and the
workspace comes from whoever is calling, never from the payload.

EventDispatchRepository is the dispatcher's, and deliberately is not scoped:
it sweeps every workspace, like the retention and reconciliation sweeps in
leka.ingestion.tasks. It must be used inside system_scope(), which says so in
one visible line — the session guard refuses the query otherwise.

JobRunRepository is for a table the session guard does not protect, on purpose
(see JobRun). It has two kinds of method and they must not be mixed up: the
transitions and passes, which act across every workspace and are the worker's,
and list_for_workspace / get_for_workspace, which are what a customer may see
and filter on for_workspace_id explicitly. Nothing else is safe to hand to a
request.

None of them commits. The caller owns the transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, Interval, case, delete, func, literal, null, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background.models import Event, EventStatus, JobQueue, JobRun, JobStatus
from leka.core.config import settings
from leka.db import Page, SortableField, WorkspaceScopedRepository, paginate

# What is written when recovery decides a worker is gone.
LEASE_EXPIRED = "lease expired: the worker holding this run stopped renewing it"

_MAX_ERROR_LENGTH = 2000


class EventRepository(WorkspaceScopedRepository):
    async def insert_once(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
        dedupe_key: str | None,
        request_id: str | None,
    ) -> Event | None:
        """Write an event, or say it was already there.

        ON CONFLICT DO NOTHING rather than looking first: a check has a race
        between the look and the write, and the constraint does not. Returns
        None when the dedupe key was already taken — which is a duplicate, not
        an error, so the caller is not made to catch anything.
        """
        statement = (
            pg_insert(Event)
            .values(
                workspace_id=self.workspace_id,
                type=event_type,
                payload=payload,
                dedupe_key=dedupe_key,
                request_id=request_id,
            )
            .on_conflict_do_nothing(constraint="uq_events_workspace_dedupe_key")
            .returning(Event)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()


class EventDispatchRepository:
    """What the dispatcher and the retention sweep ask, across every workspace."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim_pending(self, *, limit: int) -> Sequence[Event]:
        """The oldest pending events, locked for this transaction.

        FOR UPDATE SKIP LOCKED: a second dispatcher running at the same moment
        skips whatever this one holds instead of waiting for it or, worse,
        taking the same rows and enqueueing every event twice.
        """
        result = await self._session.execute(
            select(Event)
            .where(Event.status == EventStatus.PENDING)
            .order_by(Event.created_at, Event.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return result.scalars().all()

    @staticmethod
    def mark_runs_created(event: Event, *, at: datetime) -> None:
        event.status = EventStatus.RUNS_CREATED
        event.runs_created_at = at
        event.last_error = None

    @staticmethod
    def mark_unroutable(event: Event, error: str) -> None:
        event.status = EventStatus.FAILED
        event.last_error = error

    @staticmethod
    def record_failed_attempt(event: Event, error: str, *, give_up: bool) -> None:
        event.dispatch_attempts += 1
        event.last_error = error[:1000]
        if give_up:
            event.status = EventStatus.FAILED

    async def delete_settled_before(self, cutoff: datetime, *, limit: int) -> int:
        """Delete dispatched and failed events older than the cutoff.

        Never a pending one. An old pending event means the dispatcher is not
        working, and that is a thing to see, not to clean up.
        """
        stale = (
            select(Event.id)
            .where(Event.status.in_((EventStatus.RUNS_CREATED, EventStatus.FAILED)))
            .where(Event.created_at < cutoff)
            .limit(limit)
        )
        result = await self._session.execute(
            delete(Event).where(Event.id.in_(stale)).execution_options(synchronize_session=False)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]


def _after(now: datetime, seconds: Any) -> Any:
    """`now` plus a number of seconds that may itself be an SQL expression."""
    return literal(now, DateTime(timezone=True)) + func.make_interval(
        0, 0, 0, 0, 0, 0, seconds, type_=Interval
    )


def _settle(
    now: datetime, *, retry_base_seconds: int, retry_max_seconds: int, permanent: bool = False
) -> dict[str, Any]:
    """Where a run goes when an attempt ends badly: retrying, or failed.

    Decided IN the UPDATE, from the row's own counters, so that two things
    reading the same run cannot disagree about whether it has attempts left.

    The delay doubles with each attempt — base, 2x, 4x — capped. `attempts` was
    already incremented when the run was claimed, so the first failure is
    attempts = 1 and waits the base.
    """
    if permanent:
        return {
            "status": JobStatus.FAILED,
            "next_run_at": None,
            "finished_at": now,
            "locked_until": None,
        }
    attempts_left = JobRun.attempts < JobRun.max_attempts
    delay = func.least(retry_max_seconds, retry_base_seconds * func.power(2, JobRun.attempts - 1))
    return {
        "status": case((attempts_left, JobStatus.RETRYING.value), else_=JobStatus.FAILED.value),
        "next_run_at": case((attempts_left, _after(now, delay)), else_=null()),
        "finished_at": case((attempts_left, null()), else_=literal(now, DateTime(timezone=True))),
        "locked_until": None,
    }


class JobRunRepository:
    """The transitions of a run, the passes that repair the queue, and the
    history a customer may read. See the module docstring for which is which."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Creating ──────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        job: str,
        args: Sequence[object] = (),
        kwargs: dict[str, object] | None = None,
        for_workspace_id: uuid.UUID | None = None,
        event_id: uuid.UUID | None = None,
        request_id: str | None = None,
        queue: JobQueue = JobQueue.DEFAULT,
        concurrency_key: str | None = None,
        max_attempts: int | None = None,
    ) -> JobRun | None:
        """Record a run, or say it already exists.

        None means one of the two unique guarantees refused it: this event has
        already produced a run of this job, or a run is already active for this
        concurrency key. Both are "it is already happening", not errors — so
        ON CONFLICT DO NOTHING, and the caller is not made to catch anything.
        Anything ELSE that is wrong (a bad queue, a foreign key) still raises.
        """
        statement = (
            pg_insert(JobRun)
            .values(
                job=job,
                args=list(args),
                kwargs=kwargs or {},
                for_workspace_id=for_workspace_id,
                event_id=event_id,
                request_id=request_id,
                queue=queue,
                concurrency_key=concurrency_key,
                max_attempts=max_attempts or settings.job_max_attempts,
            )
            .on_conflict_do_nothing()
            .returning(JobRun)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    # ── The transitions ───────────────────────────────────────────────────
    # Each is ONE statement with the state it expects in the WHERE, and says
    # whether it changed anything. That is the whole concurrency story: two
    # workers racing, or a worker racing recovery, cannot both succeed, and the
    # loser is told so rather than left to overwrite the winner.

    async def claim(
        self, run_id: uuid.UUID, *, now: datetime, lease_seconds: float
    ) -> JobRun | None:
        """queued -> running, for exactly one caller.

        RQ delivers at least once, so two workers CAN hold the same message.
        This UPDATE is what makes only one of them act on it: the second finds
        the status already moved and gets None. A run that does not exist —
        its workspace was deleted after the job was enqueued — is also None.
        """
        result = await self._session.execute(
            update(JobRun)
            .where(JobRun.id == run_id, JobRun.status == JobStatus.QUEUED)
            .values(
                status=JobStatus.RUNNING,
                attempts=JobRun.attempts + 1,
                started_at=func.coalesce(JobRun.started_at, now),
                locked_until=now + timedelta(seconds=lease_seconds),
                next_run_at=None,
            )
            .returning(JobRun)
            .execution_options(populate_existing=True, synchronize_session=False)
        )
        return result.scalar_one_or_none()

    async def heartbeat(self, run_id: uuid.UUID, *, now: datetime, lease_seconds: float) -> bool:
        """Renew the lease. False means it was lost: recovery decided this
        worker was dead, and the worker should stop pretending otherwise."""
        result = await self._session.execute(
            update(JobRun)
            .where(JobRun.id == run_id, JobRun.status == JobStatus.RUNNING)
            .values(locked_until=now + timedelta(seconds=lease_seconds))
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def succeed(self, run_id: uuid.UUID, *, now: datetime) -> bool:
        """running -> succeeded. False if it was no longer running — a worker
        whose lease was lost, finishing late, must not overwrite recovery."""
        result = await self._session.execute(
            update(JobRun)
            .where(JobRun.id == run_id, JobRun.status == JobStatus.RUNNING)
            .values(status=JobStatus.SUCCEEDED, finished_at=now, locked_until=None)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def fail_attempt(
        self,
        run_id: uuid.UUID,
        error: str,
        *,
        now: datetime,
        retry_base_seconds: int,
        retry_max_seconds: int,
        permanent: bool = False,
    ) -> JobRun | None:
        """running -> retrying, or -> failed if it is out of attempts.

        `permanent` is for a failure no retry can fix — a job path that does not
        import will not import next time either. Returns the updated run, or
        None if it was not running.
        """
        result = await self._session.execute(
            update(JobRun)
            .where(JobRun.id == run_id, JobRun.status == JobStatus.RUNNING)
            .values(
                last_error=error[:_MAX_ERROR_LENGTH],
                **_settle(
                    now,
                    retry_base_seconds=retry_base_seconds,
                    retry_max_seconds=retry_max_seconds,
                    permanent=permanent,
                ),
            )
            .returning(JobRun)
            .execution_options(populate_existing=True, synchronize_session=False)
        )
        return result.scalar_one_or_none()

    # ── The passes that repair what the transitions cannot ────────────────

    async def expire_leases(
        self, *, now: datetime, limit: int, retry_base_seconds: int, retry_max_seconds: int
    ) -> int:
        """running -> retrying/failed for runs whose worker stopped renewing.

        A dead worker cannot report its own death. Without this the run stays
        `running` for ever — and holds its concurrency key, so nothing else can
        run in its place. A lost worker uses up an attempt, or a job that kills
        its worker every time would be retried for ever without ever looking
        like it was failing.
        """
        stale = (
            select(JobRun.id)
            .where(JobRun.status == JobStatus.RUNNING, JobRun.locked_until < now)
            .order_by(JobRun.locked_until)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(
            update(JobRun)
            .where(JobRun.id.in_(stale))
            .values(
                last_error=LEASE_EXPIRED,
                **_settle(
                    now, retry_base_seconds=retry_base_seconds, retry_max_seconds=retry_max_seconds
                ),
            )
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    async def promote_due_retries(self, *, now: datetime, limit: int) -> int:
        """retrying -> queued, for retries whose time has come.

        Back to queued WITHOUT enqueued_at: the enqueue pass, which is the only
        thing that talks to Redis, will offer it. A retry waits in the database,
        so a Redis that lost its memory did not lose it.
        """
        due = (
            select(JobRun.id)
            .where(JobRun.status == JobStatus.RETRYING, JobRun.next_run_at <= now)
            .order_by(JobRun.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(
            update(JobRun)
            .where(JobRun.id.in_(due))
            .values(status=JobStatus.QUEUED, next_run_at=None, enqueued_at=None)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    async def forget_stale_enqueues(self, *, older_than: datetime, limit: int) -> int:
        """Treat a run the queue was told about long ago, and nobody claimed, as
        never enqueued — so the enqueue pass offers it again.

        The net under a Redis that lost its memory. A duplicate message is
        harmless, because claim lets only one of them act.
        """
        stale = (
            select(JobRun.id)
            .where(
                JobRun.status == JobStatus.QUEUED,
                JobRun.enqueued_at.is_not(None),
                JobRun.enqueued_at < older_than,
            )
            .order_by(JobRun.enqueued_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(
            update(JobRun)
            .where(JobRun.id.in_(stale))
            .values(enqueued_at=None)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    async def claim_unenqueued(
        self, *, limit: int, only: Sequence[uuid.UUID] | None = None
    ) -> Sequence[JobRun]:
        """Queued runs Redis has not been told about, oldest first, locked.

        SKIP LOCKED, so two enqueue passes never take the same run.
        """
        statement = select(JobRun).where(
            JobRun.status == JobStatus.QUEUED, JobRun.enqueued_at.is_(None)
        )
        if only is not None:
            statement = statement.where(JobRun.id.in_(only))
        result = await self._session.execute(
            statement.order_by(JobRun.created_at, JobRun.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return result.scalars().all()

    @staticmethod
    def mark_enqueued(run: JobRun, *, at: datetime) -> None:
        run.enqueued_at = at

    # ── What a customer may see ───────────────────────────────────────────

    async def list_for_workspace(
        self, workspace_id: uuid.UUID, *, limit: int, cursor: str | None = None
    ) -> Page[JobRun]:
        """One workspace's history, newest first.

        Filters on for_workspace_id EXPLICITLY, and an equality never matches
        NULL — which is the point: a system run is operating data, not a
        customer's, and must never come back from here.
        """
        return await paginate(
            self._session,
            select(JobRun).where(JobRun.for_workspace_id == workspace_id),
            sort_by=SortableField(
                "created_at", JobRun.created_at, "ix_job_runs_for_workspace_id_created_at"
            ),
            id_column=JobRun.id,
            direction="desc",
            limit=limit,
            cursor=cursor,
        )

    async def get_for_workspace(self, workspace_id: uuid.UUID, run_id: uuid.UUID) -> JobRun | None:
        result = await self._session.execute(
            select(JobRun).where(JobRun.id == run_id, JobRun.for_workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()


__all__ = ["LEASE_EXPIRED", "EventDispatchRepository", "EventRepository", "JobRunRepository"]
