"""From what the systems kept, the notifications (LEKA-476).

Nothing here decides that something happened: each family reads what its
own system already kept — an intention's history, an agent run's end, an
alert's life, a source's events, a Stripe event verified and applied, a
share of the credits passed, the audit trail — after where it last read,
and says it. The same fact read twice is told once: its key is the fact's
own identity, unique in the workspace (ON CONFLICT DO NOTHING).

A family that fails is said — logged, and kept on its cursor with when and
why — and the others are read all the same; its cursor does not move, so
what it missed is read again next time.

Read by keys — when, then id — so that a burst kept at one moment (one
transaction's `now()`) is read through, page by page; and from a quarter of
an hour before where it last read, so that a long transaction committed
late is not passed over. Read again, a fact is not told again.

Read when someone looks (the bell's count, the list), at most once at a
time per workspace, and every few minutes by the schedule.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import ColumnElement, func, literal, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing import StripeEvent
from leka.capabilities import AgentRun, find
from leka.connectors import Source, SourceEvent, SourceEventType, SourceStatus
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import AuditEvent
from leka.identity import User
from leka.ingestion.enrichment.twin import LATE_AFTER
from leka.intentions import Intention, IntentionEvent
from leka.metering import CreditWarning
from leka.monitoring import MonitoringAlert, NightReview
from leka.notifications.repository import NotificationRepository, Told
from leka.platform import Workspace

logger = structlog.get_logger(__name__)

# Read for the first time: the week before, not the workspace's whole past.
FIRST_READ = timedelta(days=7)
# Read again each time, for what a long transaction committed late.
OVERLAP = timedelta(minutes=15)
# A page of facts; at most PAGES of them a time, the rest next time.
BATCH = 500
PAGES = 20
NONE = uuid.UUID(int=0)

Key = tuple[datetime, uuid.UUID]


@dataclass(frozen=True)
class Read:
    """What a family read: what to tell, the key of the last fact read —
    none when it reads no history — and how many it read."""

    told: list[Told]
    last: Key | None = None
    count: int = 0


Family = Callable[[AsyncSession, uuid.UUID, Key, datetime], Awaitable[Read]]


def _after(time: Any, ident: Any, after: Key) -> ColumnElement[bool]:
    """Facts past a key, by when then by id."""
    return tuple_(time, ident) > tuple_(literal(after[0]), literal(after[1]))


def _last(keys: Sequence[Key]) -> Key | None:
    return keys[-1] if keys else None


# ── intentions: their history ────────────────────────────────────────────────

# A move, said: what it is, how grave.
MOVES: dict[str, tuple[str, str]] = {
    "needs_clarification": ("intention.clarification_required", "warning"),
    "analysing": ("intention.analysis_started", "info"),
    "awaiting_decision": ("intention.decision_required", "warning"),
    "failed": ("intention.failed", "critical"),
    "approved": ("intention.approved", "info"),
    "rejected": ("intention.rejected", "info"),
    "completed": ("intention.completed", "success"),
}


async def _intentions(
    session: AsyncSession, workspace_id: uuid.UUID, after: Key, now: datetime
) -> Read:
    rows = (
        await session.execute(
            select(IntentionEvent, Intention.title, Intention.created_by)
            .join(Intention, Intention.id == IntentionEvent.intention_id)
            .where(
                _after(IntentionEvent.created_at, IntentionEvent.id, after),
                IntentionEvent.kind.in_(("created", "moved")),
            )
            .order_by(IntentionEvent.created_at, IntentionEvent.id)
            .limit(BATCH)
        )
    ).all()
    told: list[Told] = []
    for event, title, author in rows:
        if event.kind == "created":
            kind, severity = "intention.created", "info"
        elif event.to_status in MOVES:
            kind, severity = MOVES[event.to_status]
            # Answered: the analysis done — acted on and verified: done.
            if event.to_status == "completed" and event.from_status == "analysing":
                kind = "intention.analysis_completed"
        else:
            continue
        deciding = kind == "intention.decision_required"
        told.append(
            Told(
                key=f"intention_event:{event.id}",
                category="intention",
                kind=kind,
                severity=severity,
                occurred_at=event.at,
                params={"title": title},
                link=f"/intentions/{event.intention_id}" + ("/decision" if deciding else ""),
                to_user=author,
                # Who may decide is told too.
                to_permission="intention:approve" if deciding else None,
            )
        )
    return Read(told, _last([(event.created_at, event.id) for event, *_ in rows]), len(rows))


# ── agents: a run's end ─────────────────────────────────────────────────────


async def _agents(
    session: AsyncSession, workspace_id: uuid.UUID, after: Key, now: datetime
) -> Read:
    rows = (
        await session.scalars(
            select(AgentRun)
            .where(
                _after(AgentRun.updated_at, AgentRun.id, after),
                AgentRun.status.in_(("succeeded", "failed")),
                AgentRun.requested_by.is_not(None),
            )
            .order_by(AgentRun.updated_at, AgentRun.id)
            .limit(BATCH)
        )
    ).all()
    told: list[Told] = []
    for run in rows:
        definition = find(run.key)
        succeeded = run.status == "succeeded"
        told.append(
            Told(
                key=f"agent_run:{run.id}:{run.status}",
                category="agent",
                kind="agent.run_succeeded" if succeeded else "agent.run_failed",
                severity="success" if succeeded else "critical",
                occurred_at=run.finished_at or run.updated_at,
                params={"agent": definition.title if definition else run.key, "error": run.error},
                link=(
                    f"/intentions/{run.intention_id}/deliverable"
                    if run.intention_id
                    else f"/capabilities/{run.key}"
                ),
                to_user=run.requested_by,
            )
        )
    return Read(told, _last([(run.updated_at, run.id) for run in rows]), len(rows))


# ── monitoring: an alert's life ─────────────────────────────────────────────

GRAVITY = {"high": "critical", "medium": "warning", "low": "info"}


async def _alerts(
    session: AsyncSession, workspace_id: uuid.UUID, after: Key, now: datetime
) -> Read:
    rows = (
        await session.scalars(
            select(MonitoringAlert)
            .where(_after(MonitoringAlert.updated_at, MonitoringAlert.id, after))
            .order_by(MonitoringAlert.updated_at, MonitoringAlert.id)
            .limit(BATCH)
        )
    ).all()
    told: list[Told] = []
    for alert in rows:
        entity = alert.subject_id if alert.subject_type == "entity" else None
        link = "/environment" if entity else f"/sources/{alert.subject_id}"
        params = {"name": alert.subject_name, "trouble": alert.kind, "certainty": alert.certainty}
        # Opened again: the same thing, the same trouble, ended before.
        before = await session.scalar(
            select(func.count())
            .select_from(MonitoringAlert)
            .where(
                MonitoringAlert.workspace_id == workspace_id,
                MonitoringAlert.subject_id == alert.subject_id,
                MonitoringAlert.family == alert.family,
                MonitoringAlert.id != alert.id,
                MonitoringAlert.status == "resolved",
                MonitoringAlert.resolved_at <= alert.opened_at,
            )
        )
        told.append(
            Told(
                key=f"alert:{alert.id}:opened",
                category="monitoring",
                kind="alert.reopened" if before else "alert.triggered",
                severity=GRAVITY.get(alert.severity, "warning"),
                occurred_at=alert.opened_at,
                params=params,
                link=link,
                entity_id=entity,
            )
        )
        if alert.acknowledged_at is not None:
            told.append(
                Told(
                    key=f"alert:{alert.id}:acknowledged",
                    category="monitoring",
                    kind="alert.acknowledged",
                    severity="info",
                    occurred_at=alert.acknowledged_at,
                    params=params | {"by": await _name(session, alert.acknowledged_by)},
                    link=link,
                    entity_id=entity,
                )
            )
        if alert.status == "resolved" and alert.resolved_at is not None:
            told.append(
                Told(
                    key=f"alert:{alert.id}:resolved",
                    category="monitoring",
                    kind="alert.resolved",
                    severity="success",
                    occurred_at=alert.resolved_at,
                    params=params,
                    link=link,
                    entity_id=entity,
                )
            )
    return Read(told, _last([(alert.updated_at, alert.id) for alert in rows]), len(rows))


# ── sources: their events, and their reads gone stale ───────────────────────

SOURCE_EVENTS: dict[SourceEventType, tuple[str, str]] = {
    SourceEventType.SYNC_FAILED: ("source.sync_failed", "warning"),
    SourceEventType.SYNC_RECOVERED: ("source.sync_recovered", "success"),
}


async def _sources(
    session: AsyncSession, workspace_id: uuid.UUID, after: Key, now: datetime
) -> Read:
    rows = (
        await session.execute(
            select(SourceEvent, Source.name)
            .join(Source, Source.id == SourceEvent.source_id)
            .where(
                _after(SourceEvent.created_at, SourceEvent.id, after),
                SourceEvent.type.in_(
                    (
                        SourceEventType.SYNC_FAILED,
                        SourceEventType.SYNC_RECOVERED,
                        SourceEventType.HEALTH_CHANGED,
                    )
                ),
            )
            .order_by(SourceEvent.created_at, SourceEvent.id)
            .limit(BATCH)
        )
    ).all()
    told: list[Told] = []
    for event, name in rows:
        said = SOURCE_EVENTS.get(event.type)
        if event.type is SourceEventType.HEALTH_CHANGED:
            # Unreachable, its token refused: a person has to act. Back: said.
            current = str(event.payload.get("current") or "")
            if current == "unhealthy":
                said = ("source.disconnected", "critical")
            elif current == "healthy" and event.payload.get("previous") == "unhealthy":
                said = ("source.reconnected", "success")
        if said is None:
            continue
        told.append(
            Told(
                key=f"source_event:{event.id}",
                category="source",
                kind=said[0],
                severity=said[1],
                occurred_at=event.created_at,
                params={"name": name, "code": event.payload.get("code")},
                link=f"/sources/{event.source_id}",
                to_permission="source:manage",
            )
        )
    return Read(told, _last([(event.created_at, event.id) for event, _ in rows]), len(rows))


async def _stale(session: AsyncSession, workspace_id: uuid.UUID, after: Key, now: datetime) -> Read:
    """A source read too long ago: its data is old — once per such stretch,
    the read it dates from being the stretch's identity. No history: what is
    stale now."""
    told: list[Told] = []
    stale = (
        await session.execute(
            select(Source.id, Source.name, Source.last_synced_at).where(
                Source.status.in_((SourceStatus.ACTIVE, SourceStatus.DEGRADED)),
                Source.last_synced_at.is_not(None),
                Source.last_synced_at < now - LATE_AFTER,
            )
        )
    ).all()
    for source_id, name, last in stale:
        told.append(
            Told(
                key=f"source:{source_id}:stale:{last.isoformat()}",
                category="source",
                kind="source.stale",
                severity="warning",
                occurred_at=last + LATE_AFTER,
                params={"name": name, "last": last.isoformat()},
                link=f"/sources/{source_id}",
                to_permission="source:manage",
            )
        )
    return Read(told)


# ── billing: Stripe's events as applied, and the credits ────────────────────


async def _billing(
    session: AsyncSession, workspace_id: uuid.UUID, after: Key, now: datetime
) -> Read:
    events = (
        await session.scalars(
            select(StripeEvent)
            .where(
                StripeEvent.for_workspace_id == workspace_id,
                StripeEvent.outcome == "applied",
                _after(StripeEvent.created_at, StripeEvent.id, after),
            )
            .order_by(StripeEvent.created_at, StripeEvent.id)
            .limit(BATCH)
        )
    ).all()
    told: list[Told] = []

    def bill(event: StripeEvent, what: str, kind: str, severity: str, **params: Any) -> None:
        told.append(
            Told(
                key=f"stripe:{event.event_id}:{what}",
                category="billing",
                kind=kind,
                severity=severity,
                occurred_at=event.received_at,
                params=params,
                link="/billing",
                to_permission="workspace:update",
            )
        )

    for event in events:
        detail: dict[str, Any] = dict(event.detail or {})
        raw = detail.get("changes")
        changes: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if event.type == "invoice.payment_failed":
            bill(event, "payment_failed", "billing.payment_failed", "critical")
        if event.type == "invoice.paid" and detail.get("reason") == "subscription_cycle":
            bill(event, "renewed", "billing.renewed", "success")
        cancel = changes.get("cancel_at_period_end")
        if cancel == [False, True]:
            bill(
                event,
                "cancellation",
                "billing.cancellation_scheduled",
                "warning",
                until=changes.get("ends") or detail.get("ends"),
            )
        elif cancel == [True, False]:
            bill(event, "renewal", "billing.renewal_resumed", "info")
        plan = changes.get("plan")
        if isinstance(plan, list) and len(plan) == 2:
            bill(event, "plan", "billing.plan_changed", "info", before=plan[0], after=plan[1])
    return Read(told, _last([(e.created_at, e.id) for e in events]), len(events))


async def _credits(
    session: AsyncSession, workspace_id: uuid.UUID, after: Key, now: datetime
) -> Read:
    """A share of the month's AI credits passed (metering's own warning)."""
    told: list[Told] = []
    warnings = (
        await session.scalars(
            select(CreditWarning)
            .where(_after(CreditWarning.created_at, CreditWarning.id, after))
            .order_by(CreditWarning.created_at, CreditWarning.id)
            .limit(BATCH)
        )
    ).all()
    for warning in warnings:
        told.append(
            Told(
                key=f"credit_warning:{warning.id}",
                category="billing",
                kind="capacity.threshold",
                severity="critical" if warning.threshold >= 100 else "warning",
                occurred_at=warning.at,
                params={"threshold": warning.threshold, "period": warning.period.isoformat()},
                link="/billing",
            )
        )
    return Read(told, _last([(w.created_at, w.id) for w in warnings]), len(warnings))


# ── the night review (2026-10-29) ────────────────────────────────────────────


async def _night(session: AsyncSession, workspace_id: uuid.UUID, after: Key, now: datetime) -> Read:
    """What LEKA went through overnight, when it found something to look at:
    told to everyone who reads the environment — a quiet night tells nothing.
    Once a night (2026-10-31: a review every hour of it): the review the
    morning report took, when it took it (`reported_at`)."""
    told: list[Told] = []
    reviews = (
        await session.scalars(
            select(NightReview)
            .where(
                NightReview.reported_at.is_not(None),
                _after(NightReview.reported_at, NightReview.id, after),
            )
            .order_by(NightReview.reported_at, NightReview.id)
            .limit(BATCH)
        )
    ).all()
    for review in reviews:
        if review.trigger != "night" or not review.points:
            continue
        high = sum(1 for p in review.points if p.get("severity") == "high")
        told.append(
            Told(
                key=f"night_review:{review.id}",
                category="monitoring",
                kind="alert.night_review",
                severity="warning" if high else "info",
                occurred_at=review.at,
                params={"count": len(review.points), "high": high},
                link="/environment",
                to_permission="source:read",
            )
        )
    return Read(
        told, _last([(r.reported_at, r.id) for r in reviews if r.reported_at]), len(reviews)
    )


# ── the workspace: who joined, whose role changed ───────────────────────────


async def _workspace(
    session: AsyncSession, workspace_id: uuid.UUID, after: Key, now: datetime
) -> Read:
    rows = (
        await session.scalars(
            select(AuditEvent)
            .where(
                _after(AuditEvent.created_at, AuditEvent.id, after),
                AuditEvent.action.in_(("member.role_changed", "member.joined")),
                AuditEvent.outcome == "success",
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
            .limit(BATCH)
        )
    ).all()
    told: list[Told] = []
    for event in rows:
        target = _uuid(event.target_id)
        if event.action == "member.role_changed" and target is not None:
            told.append(
                Told(
                    key=f"audit:{event.id}",
                    category="workspace",
                    kind="workspace.role_changed",
                    severity="info",
                    occurred_at=event.at,
                    params={
                        "before": event.detail.get("before"),
                        "after": event.detail.get("after"),
                    },
                    link="/settings",
                    to_user=target,
                )
            )
        elif event.action == "member.joined":
            told.append(
                Told(
                    key=f"audit:{event.id}",
                    category="workspace",
                    kind="workspace.member_joined",
                    severity="info",
                    occurred_at=event.at,
                    params={"name": event.target_label or await _name(session, target)},
                    link="/settings",
                    to_permission="member:invite",
                )
            )
    return Read(told, _last([(event.created_at, event.id) for event in rows]), len(rows))


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def _name(session: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    row = (
        await session.execute(
            select(User.first_name, User.last_name, User.email).where(User.id == user_id)
        )
    ).first()
    if row is None:
        return None
    first, last, email = row
    return " ".join(p for p in (first, last) if p) or email


FAMILIES: dict[str, Family] = {
    "intentions": _intentions,
    "agents": _agents,
    "alerts": _alerts,
    "sources": _sources,
    "stale": _stale,
    "billing": _billing,
    "credits": _credits,
    "workspace": _workspace,
    "night": _night,
}


# ── reading them in ──────────────────────────────────────────────────────────


async def project(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    now: datetime | None = None,
    families: dict[str, Family] | None = None,
) -> int:
    """Read every family's new facts into notifications. Skipped when
    another reading of this workspace is under way: it tells the same."""
    moment = now or datetime.now(UTC)
    taken = await session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"notifications:{workspace_id}"},
    )
    if not taken:
        return 0
    told = 0
    kept = NotificationRepository(session, workspace_id)
    for family, read in (families or FAMILIES).items():
        cursor = await kept.cursor(family, read_to=moment - FIRST_READ)
        after: Key = (cursor.read_to - OVERLAP, NONE)
        try:
            async with session.begin_nested():
                for _ in range(PAGES):
                    found = await read(session, workspace_id, after, moment)
                    told += await kept.keep(found.told)
                    if found.last is None:
                        break
                    after = found.last
                    if found.count < BATCH:
                        break
        except Exception as error:
            # Said, never silent: logged, and on its cursor. What it missed
            # is read again next time — the cursor stays where it was.
            logger.warning(
                "notifications_not_read", workspace=str(workspace_id), family=family, exc_info=True
            )
            cursor.failed_at = moment
            cursor.failure = f"{type(error).__name__}: {error}"[:500]
            continue
        cursor.read_to = max(cursor.read_to, after[0])
        cursor.failed_at = None
        cursor.failure = None
    await session.flush()
    return told


async def sweep(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace, read — one that fails is logged, the others read."""
    with system_scope():
        async with session_factory() as session:
            workspaces = list((await session.scalars(select(Workspace.id))).all())
    told = 0
    for workspace_id in workspaces:
        try:
            with workspace_scope(workspace_id):
                async with session_factory() as session:
                    told += await project(session, workspace_id, now=now)
                    await session.commit()
        except Exception:
            logger.exception("notifications_sweep_failed", workspace=str(workspace_id))
    return {"workspaces": len(workspaces), "told": told}


def run_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(sweep())
