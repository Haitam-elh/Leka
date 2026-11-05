"""The activity journal: what happened across LEKA, once each (LEKA-544).

Adoption, activation and retention need a history the product does not keep
in one place: a session is purged when it expires, a sign-in is copied into
each of a person's workspaces and goes with their retention, a run's figures
live in three tables. So the journal is DERIVED: every five minutes a sweep
reads, from each table that already says it, what happened since it last
read, and writes one `activity_events` row per fact — never twice, whatever
runs again, because each row has its `dedupe_key` (ON CONFLICT DO NOTHING).
A fact a module records later than it happened is caught by a ten-minute
overlap; a first run reads the whole history.

Nothing is changed where it is written: no module calls this, no request
waits for it. What is kept is minimal and never sensitive — which kind,
about which organisation and person, when, the row it was read from, the
request id when its source kept one, and a few figures (an agent's key, a
duration, credits). Never what anyone wrote, no address, no browser.

  kind                   read from          when
  user.signed_up         users              created
  user.signed_in         sessions           a session opened
  user.active            sessions           seen on a day (one per person and day)
  workspace.created      workspaces         created
  member.joined          memberships        a seat taken
  subscription.started   stripe_events      customer.subscription.created
  subscription.changed   stripe_events      customer.subscription.updated
  subscription.canceled  stripe_events      customer.subscription.deleted
  payment.succeeded      stripe_events      invoice.paid
  payment.failed         stripe_events      invoice.payment_failed
  refund.issued          stripe_events      charge.refunded
  intention.created      intentions         asked
  intention.completed    intention_events   moved to completed
  intention.failed       intention_events   moved to failed
  intention.cancelled    intention_events   moved to cancelled or rejected
  agent_run.succeeded    agent_runs         finished
  agent_run.failed       agent_runs         finished
  credits.consumed       usage_records      metered (kept up to date: a run
                                            metered again is the same row)
  source.connected       sources            created
  sync.failed            sync_runs          a pass that failed

Kept 25 months, for a year compared with the one before; the sweep forgets
what is older, and the admin idempotency keys past a week.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from leka.admin.models import ActivityEvent, ActivityWatermark, AdminIdempotencyKey
from leka.billing import StripeEvent
from leka.capabilities import AgentRun
from leka.connectors import Source
from leka.core.config import settings
from leka.db import session_factory, system_scope
from leka.identity import Session, User
from leka.ingestion import SyncRun
from leka.intentions import Intention, IntentionEvent
from leka.metering import UsageRecord
from leka.platform import Membership, Workspace

logger = structlog.get_logger(__name__)

OVERLAP = timedelta(minutes=10)
BATCH = 2000
RETENTION = timedelta(days=760)
IDEMPOTENCY_RETENTION = timedelta(days=7)
EPOCH = datetime(2020, 1, 1, tzinfo=UTC)

STRIPE_KINDS = {
    "customer.subscription.created": "subscription.started",
    "customer.subscription.updated": "subscription.changed",
    "customer.subscription.deleted": "subscription.canceled",
    "invoice.paid": "payment.succeeded",
    "invoice.payment_failed": "payment.failed",
    "charge.refunded": "refund.issued",
}
INTENTION_ENDS = {
    "completed": "intention.completed",
    "failed": "intention.failed",
    "cancelled": "intention.cancelled",
    "rejected": "intention.cancelled",
}
RUN_ENDS = {"succeeded": "agent_run.succeeded", "failed": "agent_run.failed"}

Values = dict[str, Any]


def _event(
    kind: str,
    at: datetime,
    dedupe_key: str,
    *,
    workspace_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    ref: str | None = None,
    request_id: str | None = None,
    properties: dict[str, object] | None = None,
) -> Values:
    return {
        "id": uuid.uuid4(),
        "kind": kind,
        "at": at,
        "for_workspace_id": workspace_id,
        "user_id": user_id,
        "ref": ref,
        "request_id": request_id,
        "properties": properties or {},
        "dedupe_key": dedupe_key[:200],
    }


@dataclass(frozen=True)
class JournalSource:
    """One table read into the journal: what to read, by which moment, and
    what each row says."""

    name: str
    column: InstrumentedAttribute[Any]
    statement: Callable[[], Select[Any]]
    facts: Callable[[Any], list[Values]]
    # Facts a later reading may correct (a run metered again): updated, not skipped.
    refresh: bool = False


def _signed_up(user: User) -> list[Values]:
    return [
        _event(
            "user.signed_up",
            user.created_at,
            f"user.signed_up:{user.id}",
            user_id=user.id,
            ref=f"user:{user.id}",
        )
    ]


def _signed_in(session: Session) -> list[Values]:
    return [
        _event(
            "user.signed_in",
            session.created_at,
            f"user.signed_in:{session.id}",
            workspace_id=session.active_workspace_id,
            user_id=session.user_id,
            ref=f"session:{session.id}",
        )
    ]


def _active(session: Session) -> list[Values]:
    day = session.last_seen_at.astimezone(UTC).date()
    return [
        _event(
            "user.active",
            session.last_seen_at,
            f"user.active:{session.user_id}:{day.isoformat()}",
            workspace_id=session.active_workspace_id,
            user_id=session.user_id,
        )
    ]


def _workspace(workspace: Workspace) -> list[Values]:
    return [
        _event(
            "workspace.created",
            workspace.created_at,
            f"workspace.created:{workspace.id}",
            workspace_id=workspace.id,
            ref=f"workspace:{workspace.id}",
            properties={"demo": workspace.demo},
        )
    ]


def _joined(seat: Membership) -> list[Values]:
    return [
        _event(
            "member.joined",
            seat.created_at,
            f"member.joined:{seat.id}",
            workspace_id=seat.workspace_id,
            user_id=seat.user_id,
            ref=f"membership:{seat.id}",
            properties={"role": str(seat.role)},
        )
    ]


def _stripe(event: StripeEvent) -> list[Values]:
    kind = STRIPE_KINDS.get(event.type)
    if kind is None:
        return []
    return [
        _event(
            kind,
            event.received_at,
            f"stripe:{event.event_id}",
            workspace_id=event.for_workspace_id,
            ref=f"stripe_event:{event.event_id}",
            properties={"type": event.type, "outcome": event.outcome},
        )
    ]


def _asked(intention: Intention) -> list[Values]:
    return [
        _event(
            "intention.created",
            intention.created_at,
            f"intention.created:{intention.id}",
            workspace_id=intention.workspace_id,
            user_id=intention.created_by,
            ref=f"intention:{intention.id}",
            properties={"kind": str(intention.kind) if intention.kind else None},
        )
    ]


def _ended(event: IntentionEvent) -> list[Values]:
    kind = INTENTION_ENDS.get(str(event.to_status)) if event.to_status else None
    if kind is None:
        return []
    return [
        _event(
            kind,
            event.at,
            f"{kind}:{event.intention_id}:{event.sequence}",
            workspace_id=event.workspace_id,
            user_id=event.by,
            ref=f"intention:{event.intention_id}",
        )
    ]


def _run(run: AgentRun) -> list[Values]:
    kind = RUN_ENDS.get(run.status)
    if kind is None or run.finished_at is None:
        return []
    duration = (
        int((run.finished_at - run.started_at).total_seconds() * 1000) if run.started_at else None
    )
    return [
        _event(
            kind,
            run.finished_at,
            f"agent_run:{run.id}",
            workspace_id=run.workspace_id,
            user_id=run.requested_by,
            ref=f"agent_run:{run.id}",
            properties={"agent": run.key, "model": run.model, "duration_ms": duration},
        )
    ]


def _consumed(record: UsageRecord) -> list[Values]:
    cost = record.leka_cost_usd
    return [
        _event(
            "credits.consumed",
            record.ended_at or record.started_at,
            f"credits.consumed:{record.workspace_id}:{record.execution}",
            workspace_id=record.workspace_id,
            user_id=record.user_id,
            ref=record.execution,
            properties={
                "kind": record.kind,
                "subject": record.subject,
                "credits": round(cost / settings.credit_usd, 4) if cost is not None else None,
                "cost_status": record.cost_status,
            },
        )
    ]


def _connected(source: Source) -> list[Values]:
    return [
        _event(
            "source.connected",
            source.created_at,
            f"source.connected:{source.id}",
            workspace_id=source.workspace_id,
            user_id=source.created_by,
            ref=f"source:{source.id}",
            properties={"kind": str(source.kind)},
        )
    ]


def _sync_failed(run: SyncRun) -> list[Values]:
    if run.finished_at is None:
        return []
    return [
        _event(
            "sync.failed",
            run.finished_at,
            f"sync.failed:{run.id}",
            workspace_id=run.workspace_id,
            ref=f"sync_run:{run.id}",
            properties={"capability": run.capability},
        )
    ]


SOURCES: tuple[JournalSource, ...] = (
    JournalSource("users", User.created_at, lambda: select(User), _signed_up),
    JournalSource("sessions", Session.created_at, lambda: select(Session), _signed_in),
    JournalSource("presence", Session.last_seen_at, lambda: select(Session), _active),
    JournalSource("workspaces", Workspace.created_at, lambda: select(Workspace), _workspace),
    JournalSource("memberships", Membership.created_at, lambda: select(Membership), _joined),
    JournalSource(
        "stripe",
        StripeEvent.received_at,
        lambda: select(StripeEvent).where(StripeEvent.type.in_(STRIPE_KINDS)),
        _stripe,
    ),
    JournalSource("intentions", Intention.created_at, lambda: select(Intention), _asked),
    JournalSource(
        "intention_ends",
        IntentionEvent.at,
        lambda: select(IntentionEvent).where(IntentionEvent.to_status.in_(INTENTION_ENDS)),
        _ended,
    ),
    JournalSource(
        "agent_runs",
        AgentRun.finished_at,
        lambda: select(AgentRun).where(AgentRun.status.in_(RUN_ENDS)),
        _run,
    ),
    JournalSource(
        "usage", UsageRecord.updated_at, lambda: select(UsageRecord), _consumed, refresh=True
    ),
    JournalSource("sources", Source.created_at, lambda: select(Source), _connected),
    JournalSource(
        "sync_failures",
        SyncRun.finished_at,
        lambda: select(SyncRun).where(SyncRun.status == "failed"),
        _sync_failed,
    ),
)


async def _watermark(session: AsyncSession, name: str) -> datetime:
    row = await session.scalar(select(ActivityWatermark).where(ActivityWatermark.source == name))
    return row.read_to if row else EPOCH


async def _advance(session: AsyncSession, name: str, read_to: datetime) -> None:
    await session.execute(
        insert(ActivityWatermark)
        .values(id=uuid.uuid4(), source=name, read_to=read_to)
        .on_conflict_do_update(
            constraint="uq_activity_watermarks_source", set_={"read_to": read_to}
        )
    )


async def _write(session: AsyncSession, values: Sequence[Values], *, refresh: bool) -> int:
    if not values:
        return 0
    statement = insert(ActivityEvent).values(list(values))
    if refresh:
        statement = statement.on_conflict_do_update(
            constraint="uq_activity_events_dedupe",
            set_={"properties": statement.excluded.properties, "at": statement.excluded.at},
        )
    else:
        statement = statement.on_conflict_do_nothing(constraint="uq_activity_events_dedupe")
    result = await session.execute(statement.returning(ActivityEvent.id))
    return len(result.all())


async def read_source(session: AsyncSession, source: JournalSource, *, now: datetime) -> int:
    """Read one table into the journal, from its watermark to now."""
    since = await _watermark(session, source.name)
    start = since - OVERLAP if since > EPOCH else EPOCH
    written = 0
    cursor = start
    while True:
        rows = (
            await session.scalars(
                source.statement()
                .where(source.column >= cursor, source.column <= now)
                .order_by(source.column)
                .limit(BATCH)
            )
        ).all()
        values: dict[str, Values] = {}
        for row in rows:
            for fact in source.facts(row):
                # One fact per key in a batch: Postgres refuses a statement
                # that would touch the same row twice.
                values.setdefault(str(fact["dedupe_key"]), fact)
        written += await _write(session, list(values.values()), refresh=source.refresh)
        if len(rows) < BATCH:
            break
        last = getattr(rows[-1], source.column.key)
        if last <= cursor:
            break
        cursor = last
    await _advance(session, source.name, now)
    return written


async def sweep(*, now: datetime | None = None) -> dict[str, int]:
    """Every source read into the journal; what is past its keeping forgotten.

    Read up to the database's clock, not this process's: the rows say when
    they were made by the database's, and a process a few milliseconds late
    would leave out what was written just before it looked."""
    written: dict[str, int] = {}
    with system_scope():
        if now is None:
            async with session_factory() as session:
                found = await session.scalar(select(func.clock_timestamp()))
            moment = found or datetime.now(UTC)
        else:
            moment = now
        for source in SOURCES:
            async with session_factory() as session:
                try:
                    written[source.name] = await read_source(session, source, now=moment)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    # One table that cannot be read does not stop the others,
                    # and its watermark stays where it was: read again next time.
                    logger.exception("activity_source_failed", source=source.name)
                    written[source.name] = -1
        async with session_factory() as session:
            await session.execute(
                delete(ActivityEvent).where(ActivityEvent.at < moment - RETENTION)
            )
            await session.execute(
                delete(AdminIdempotencyKey).where(
                    AdminIdempotencyKey.created_at < moment - IDEMPOTENCY_RETENTION
                )
            )
            await session.commit()
    logger.info("activity_swept", written=written)
    return written


def run_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(sweep())
