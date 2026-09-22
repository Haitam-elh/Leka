"""Tables owned by the background module: events, and the record of running them.

Two tables, and the line between them is the point.

    events     what HAPPENED, in a customer's workspace. Written in the same
               transaction as the change that caused it, so an event exists if
               and only if the change does. Belongs to one workspace.

    job_runs   what was DONE about it, and how that went. One row per unit of
               work: its state, its attempts, its last error. Belongs to whoever
               it worked for — or to nobody, for a sweep.

An event is handed to the queue in two hops, and each hop is a database write
first: the dispatcher turns an event into job_runs rows (durable, deduplicated by
`uq_job_runs_event_id_job`), and a separate pass puts those rows on the Redis
queue and stamps `enqueued_at`. Redis is never on the path of a transaction, and
a run the queue never heard of is a row saying so.

See docs/adr/013-events-and-job-runs.md for why an outbox rather than a broker.

AT-LEAST-ONCE, NOT EXACTLY-ONCE. A dispatcher can die between creating the runs
and marking the event dispatched, and will then do it again; RQ can deliver one
message twice. What the schema and the claim guarantee is that neither becomes a
second EXECUTION: the run is unique per (event, job), and `claim` moves it out of
`queued` in a single UPDATE that only one worker can win. A job that ran half and
was retried is the job's own idempotence to provide.

THIS MODULE DOES NOT IMPORT leka.platform, and cannot: it sits below it, so that
platform can use it. So an event payload and a job's arguments are JSON — strings,
numbers, identifiers — never a typed reference to a workspace or a source. That is
not a limit to work around. RQ serialises job arguments to JSON anyway.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class EventStatus(enum.StrEnum):
    """Where an event is on its way to the queue.

    `failed` is FINAL: the dispatcher gave up. An event that could not be
    handed over YET is still `pending`.
    """

    PENDING = "pending"
    RUNS_CREATED = "runs_created"
    FAILED = "failed"


class JobStatus(enum.StrEnum):
    """Where a run is in its life. See TRANSITIONS for every way out.

    `queued`     waiting for a worker. It may or may not have reached Redis yet:
                 that is `enqueued_at`, a different question.
    `running`    a worker claimed it and holds a lease.
    `retrying`   an attempt failed and another is due at `next_run_at`. The run
                 waits IN THE DATABASE, not in Redis: a Redis that loses its
                 memory must not lose a retry.
    `succeeded`  final.
    `failed`     final — out of attempts, or a failure no retry can fix.

    `retrying` is not `queued`. A run that failed and will be tried again is
    `retrying`; one that is simply waiting for a worker is `queued`. Collapsing
    them would make "is this going to run again by itself?" unanswerable from the
    history, and a "failed" that means "failed for now" is how a dashboard ends up
    reporting an incident that has already resolved itself.
    """

    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# The state machine, as data. Tests assert three things about it — every status
# is reachable, no status can get stuck, the final ones are terminal — and that
# the repository moves a run only along these edges.
TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    # a worker claims it
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING}),
    # finished; failed an attempt with attempts left; out of attempts (or a
    # failure that no retry can fix); or the worker died — same two exits as a
    # failed attempt, and a lost worker uses up an attempt
    JobStatus.RUNNING: frozenset({JobStatus.SUCCEEDED, JobStatus.RETRYING, JobStatus.FAILED}),
    # the retry is due and goes back to waiting for a worker
    JobStatus.RETRYING: frozenset({JobStatus.QUEUED}),
    # A failed run is failed for good: retrying it makes a NEW run, so the
    # history of what happened stays true.
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
}

FINAL_STATUSES = frozenset(status for status, exits in TRANSITIONS.items() if not exits)

# The statuses in which a run still holds its concurrency key.
ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYING)


class JobQueue(enum.StrEnum):
    """The three queues, in the order a worker drains them.

    RQ has no other notion of priority: a worker started with
    `rq worker leka:high leka leka:low` empties the first before it looks at the
    next. HIGH is work a person is waiting for; LOW is the sweeps.
    """

    HIGH = "leka:high"
    DEFAULT = "leka"
    LOW = "leka:low"


def _values(enum_class: type[enum.StrEnum]) -> list[str]:
    """Store the enum VALUE, not the member name (see connectors.models)."""
    return [member.value for member in enum_class]


def _enum(enum_class: type[enum.StrEnum], name: str) -> Enum:
    """Text with a CHECK constraint, not a PostgreSQL ENUM type (ADR 006).

    The CHECK is declared explicitly in __table_args__ beside the others, so
    that everything the database refuses is in one visible list.
    """
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        length=50,
        values_callable=_values,
    )


def _in(column: str, enum_class: type[enum.StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_class)
    return f"{column} IN ({values})"


class Event(Base, WorkspaceScopedMixin):
    """Something that happened in one customer's workspace.

    Small on purpose. The payload says WHAT happened and to WHICH thing — a
    source id, a deployment id — never the data itself. Raw material belongs
    in the object store (ADR 010); an event carrying it would make this the
    second largest table in the product.
    """

    __tablename__ = "events"
    __table_args__ = (
        # What tables that point at an event reference, so that the pointer can
        # carry the workspace too (the house pattern, as sources has).
        UniqueConstraint("workspace_id", "id", name="uq_events_workspace_id_id"),
        # A webhook delivered twice becomes one event. Per workspace, so that
        # two customers producing the same key cannot learn about each other.
        # NULL keys are distinct in PostgreSQL, which is exactly right: an
        # event with no key has nothing to be a duplicate OF.
        UniqueConstraint("workspace_id", "dedupe_key", name="uq_events_workspace_dedupe_key"),
        # The dispatcher asks: what is pending, oldest first, across every
        # workspace. Retention asks: what is dispatched and older than N days.
        Index("ix_events_status_created_at", "status", "created_at"),
        CheckConstraint(_in("status", EventStatus), name="status"),
        CheckConstraint("length(type) > 0", name="type_not_empty"),
        CheckConstraint("dispatch_attempts >= 0", name="dispatch_attempts_not_negative"),
    )

    type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # The request that caused this, if there was one (LEKA-333). None from a
    # worker, a migration or a test — and that is a real answer, not a gap.
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[EventStatus] = mapped_column(
        _enum(EventStatus, "status"), nullable=False, server_default=EventStatus.PENDING.value
    )
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    runs_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


_ACTIVE = ", ".join(f"'{status.value}'" for status in ACTIVE_JOB_STATUSES)


class JobRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One unit of background work, and everything that happened to it.

    NO `workspace_id`, AND THAT IS DELIBERATE. A sweep serves every customer and
    belongs to none, so its owner is NULL — and a nullable `workspace_id` is the
    one thing test_workspace_id_is_never_nullable exists to forbid: it looks like
    the isolation column while the session guard, which only protects models
    inheriting WorkspaceScopedMixin, ignores it. So the column is called
    `for_workspace_id`. Nobody will mistake it for the guard, and the table is
    listed as tenant-free in test_tenant_isolation, with the reason, like
    sessions and email_tokens.

    Whatever exposes this history filters on `for_workspace_id` explicitly and
    never returns the NULL rows: a system run is operating data, not a
    customer's. JobRunRepository.list_for_workspace is that filter, and a test
    holds it there.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        # (The single-column FK on for_workspace_id below cascades; this
        # composite one is what pins an event to the SAME workspace.)
        ForeignKeyConstraint(
            ["for_workspace_id", "event_id"],
            ["events.workspace_id", "events.id"],
            name="fk_job_runs_workspace_event",
            # Events are pruned on a schedule; the history is not. Only event_id
            # is cleared — a plain SET NULL would null for_workspace_id too and
            # quietly turn a customer's run into a system run. Needs PostgreSQL 15.
            ondelete="SET NULL (event_id)",
        ),
        # Idempotency of the DISPATCH: one event yields one run per job, so a
        # dispatcher that dies after creating the runs and tries again gets a
        # refusal, not a second execution. NULL event_ids are distinct.
        UniqueConstraint("event_id", "job", name="uq_job_runs_event_id_job"),
        # At most one ACTIVE run per concurrency key, per owner. Two indexes
        # because NULLs are distinct in a unique index: with one, two workers
        # could run the same retention sweep at once.
        Index(
            "uq_job_runs_active_key_workspace",
            "for_workspace_id",
            "concurrency_key",
            unique=True,
            postgresql_where=text(f"for_workspace_id IS NOT NULL AND status IN ({_ACTIVE})"),
        ),
        Index(
            "uq_job_runs_active_key_system",
            "concurrency_key",
            unique=True,
            postgresql_where=text(f"for_workspace_id IS NULL AND status IN ({_ACTIVE})"),
        ),
        # A customer's history, most recent first.
        Index("ix_job_runs_for_workspace_id_created_at", "for_workspace_id", "created_at"),
        # What the retry pass asks: which retries are due.
        Index(
            "ix_job_runs_retrying_next_run_at",
            "next_run_at",
            postgresql_where=text("status = 'retrying'"),
        ),
        # What recovery asks: which running jobs have lost their worker.
        Index(
            "ix_job_runs_running_locked_until",
            "locked_until",
            postgresql_where=text("status = 'running'"),
        ),
        # What the enqueue pass asks: runs Redis has not been told about yet.
        Index(
            "ix_job_runs_unenqueued",
            "created_at",
            postgresql_where=text("status = 'queued' AND enqueued_at IS NULL"),
        ),
        # What the stale pass asks: runs Redis was told about long ago.
        Index(
            "ix_job_runs_queued_enqueued_at",
            "enqueued_at",
            postgresql_where=text("status = 'queued' AND enqueued_at IS NOT NULL"),
        ),
        CheckConstraint(_in("status", JobStatus), name="status"),
        CheckConstraint(_in("queue", JobQueue), name="queue"),
        # 0 reads as "disabled" to whoever types it and "never try" to the code.
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="attempts_in_range"),
        # With for_workspace_id NULL the composite foreign key is not checked at
        # all (MATCH SIMPLE), so an event reference with no workspace beside it
        # would be unconstrained.
        CheckConstraint(
            "event_id IS NULL OR for_workspace_id IS NOT NULL", name="event_requires_workspace"
        ),
    )

    # clock_timestamp(), not the mixin's now(): now() is the start of the
    # TRANSACTION, so every run one dispatcher pass creates would share a
    # created_at and the order the events arrived in — which is the order the
    # runs are offered in — would be lost.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    for_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # A dotted path, never an import: leka.background.jobs explains why.
    job: Mapped[str] = mapped_column(String(300), nullable=False)
    args: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    kwargs: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    queue: Mapped[JobQueue] = mapped_column(
        _enum(JobQueue, "queue"), nullable=False, server_default=JobQueue.DEFAULT.value
    )

    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "status"), nullable=False, server_default=JobStatus.QUEUED.value
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")

    concurrency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # When a retry becomes due, and until when a worker holds the lease on a
    # running job. A worker that dies stops renewing it; recovery notices.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # When the queue last accepted this run. NULL means it has not reached Redis:
    # the run is durable, the message is not, and the enqueue pass takes it.
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
