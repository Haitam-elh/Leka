"""Incidents and the team's notifications (LEKA-556): the operational
problems LEKA's team must deal with, in one place, each about the
organisation it concerns (none: the platform).

THE WATCH (`watch`, every five minutes, after the activity journal's sweep)
reads what LEKA CORE already records — never a figure of its own:

  category                  from                                  cleared when
  intention_failed          activity journal: intention.failed    it completes after all
  agent_failed              activity journal: agent_run.failed    the agent succeeds again there
                            (one per organisation and agent)
  sync_failed               activity journal: sync.failed         its source is read again
                            (one per source)
  integration_disconnected  sources in error or unhealthy         the source is healthy again
  payment_failed            billing_payments, an attempt failed   its invoice is paid or void
                            (one per invoice)
  credits                   the month's credits, exhausted        no longer exhausted
  api_error                 the API's 500s (leka.ops.api_errors)  someone resolves it
                            (one per route and exception)
  platform                  the ops watch's rules firing          the rule stops firing

NEVER TWICE: `fingerprint` names a problem, unique among the open incidents
(new, in progress); a same problem adds an occurrence to the open one, each
fact counted once (its `dedupe_key`). Three in a day make it recurring: said,
its severity raised one step, once. A problem back after its incident was
resolved or closed opens a new one, which names the one before.

SEVERITY: critical (someone acts now), high (today), medium, low. STATUS:
new, in progress, resolved, closed. Resolved may be taken up again; closed is
final. Resolved by LEKA when the problem went, said in its history.

THE NOTIFICATIONS, once each (`dedupe_key`), read by each admin on their own:
a critical incident, a payment failed, an integration disconnected, errors
repeated, credits near their limit (past the first warning of the month), a
consumption out of the ordinary (a day's credits past three times the
average day of the four weeks before, and past MIN_ABNORMAL).

Demonstration organisations are left out. Never what a customer wrote, never
a secret: names, codes and ids, diagnostics scanned again.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import Float, Select, cast, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.models import (
    OPEN_STATUSES,
    SEVERITIES,
    ActivityEvent,
    ActivityWatermark,
    AdminAccount,
    AdminNotification,
    AdminNotificationRead,
    Incident,
    IncidentEvent,
)
from leka.admin.reads import _like, _organisation_names, credits_of, diagnostic_of
from leka.admin.schemas import (
    AdminNotificationRow,
    IncidentAssignee,
    IncidentChange,
    IncidentEventRow,
    IncidentRecord,
    IncidentRow,
    IncidentSummary,
    OrganisationRef,
)
from leka.billing import BillingInvoice, BillingPayment
from leka.connectors import HealthStatus, Source, SourceStatus
from leka.db import session_factory, system_scope
from leka.ingestion import SyncRun, SyncRunOutcome
from leka.ops import drain_api_errors, firing_now
from leka.platform import Workspace

logger = structlog.get_logger(__name__)

OVERLAP = timedelta(minutes=10)
RECURRING_AFTER = 3
RECURRING_WITHIN = timedelta(hours=24)
MIN_ABNORMAL = 20.0
ABNORMAL_TIMES = 3.0
INCIDENTS_KEPT = timedelta(days=760)
NOTIFICATIONS_KEPT = timedelta(days=400)
# Severity, the least first: raised one step when recurring.
LADDER = tuple(reversed(SEVERITIES))
TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"in_progress", "resolved", "closed"}),
    "in_progress": frozenset({"resolved", "closed"}),
    # Taken up again, or closed for good.
    "resolved": frozenset({"in_progress", "closed"}),
    "closed": frozenset(),
}
ACTIVITY_KINDS = (
    "intention.failed",
    "intention.completed",
    "agent_run.failed",
    "agent_run.succeeded",
    "sync.failed",
)


class IncidentError(ValueError):
    """A change an incident does not take: why, in a word (`code`)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Signal:
    """A problem seen: an occurrence (`dedupe_key`, counted once), or a state
    that holds (no key: opened once, never counted again)."""

    category: str
    fingerprint: str
    workspace_id: uuid.UUID | None
    severity: str
    at: datetime
    technical_id: str | None = None
    detail: dict[str, object] = field(default_factory=dict)
    dedupe_key: str | None = None


def _real(column: Any) -> Any:
    return or_(
        column.is_(None), column.not_in(select(Workspace.id).where(Workspace.demo.is_(True)))
    )


def _raised(severity: str) -> str:
    rank = LADDER.index(severity) if severity in LADDER else 0
    return LADDER[min(rank + 1, len(LADDER) - 1)]


async def _notify(
    session: AsyncSession,
    kind: str,
    *,
    severity: str,
    at: datetime,
    dedupe_key: str,
    workspace_id: uuid.UUID | None = None,
    incident_id: uuid.UUID | None = None,
    detail: dict[str, object] | None = None,
) -> bool:
    written = await session.scalar(
        insert(AdminNotification)
        .values(
            id=uuid.uuid4(),
            kind=kind,
            severity=severity,
            at=at,
            for_workspace_id=workspace_id,
            incident_id=incident_id,
            dedupe_key=dedupe_key[:300],
            detail=detail or {},
        )
        .on_conflict_do_nothing(constraint="uq_admin_notifications_dedupe")
        .returning(AdminNotification.id)
    )
    return written is not None


async def _event(
    session: AsyncSession,
    incident: Incident,
    kind: str,
    at: datetime,
    *,
    dedupe_key: str | None = None,
    detail: dict[str, object] | None = None,
    admin_id: uuid.UUID | None = None,
    admin_email: str | None = None,
) -> bool:
    """Its history, a fact once: False when it was already kept."""
    written = await session.scalar(
        insert(IncidentEvent)
        .values(
            id=uuid.uuid4(),
            incident_id=incident.id,
            kind=kind,
            at=at,
            admin_id=admin_id,
            admin_email=admin_email,
            dedupe_key=dedupe_key[:300] if dedupe_key else None,
            detail=detail or {},
        )
        .on_conflict_do_nothing(constraint="uq_admin_incident_events_dedupe")
        .returning(IncidentEvent.id)
    )
    return written is not None


async def _open(session: AsyncSession, fingerprint: str) -> Incident | None:
    found: Incident | None = await session.scalar(
        select(Incident).where(
            Incident.fingerprint == fingerprint, Incident.status.in_(OPEN_STATUSES)
        )
    )
    return found


async def _said_on_open(session: AsyncSession, incident: Incident, at: datetime) -> None:
    """What the team is told when an incident opens or becomes critical."""
    common = {"workspace_id": incident.for_workspace_id, "incident_id": incident.id}
    detail = {"number": incident.number, "category": incident.category, **incident.detail}
    if incident.severity == "critical":
        await _notify(
            session,
            "critical_incident",
            severity="critical",
            at=at,
            dedupe_key=f"critical_incident:{incident.id}",
            detail=detail,
            **common,
        )
    if incident.category == "payment_failed":
        await _notify(
            session,
            "payment_failed",
            severity=incident.severity,
            at=at,
            dedupe_key=f"payment_failed:{incident.id}",
            detail=detail,
            **common,
        )
    if incident.category == "integration_disconnected":
        await _notify(
            session,
            "integration_disconnected",
            severity=incident.severity,
            at=at,
            dedupe_key=f"integration_disconnected:{incident.id}",
            detail=detail,
            **common,
        )


async def apply(session: AsyncSession, signal: Signal) -> str | None:
    """A problem seen: opened, or counted on the incident open for it.
    Returns what was done: opened, occurred; none for a fact already kept."""
    incident = await _open(session, signal.fingerprint)
    if incident is None:
        if signal.dedupe_key and await session.scalar(
            select(IncidentEvent.id).where(IncidentEvent.dedupe_key == signal.dedupe_key)
        ):
            return None
        previous = await session.scalar(
            select(Incident.id)
            .where(Incident.fingerprint == signal.fingerprint)
            .order_by(Incident.created_at.desc())
            .limit(1)
        )
        incident = Incident(
            id=uuid.uuid4(),
            for_workspace_id=signal.workspace_id,
            category=signal.category,
            severity=signal.severity,
            status="new",
            fingerprint=signal.fingerprint[:300],
            technical_id=signal.technical_id,
            detail=signal.detail,
            occurrences=1,
            first_seen_at=signal.at,
            last_seen_at=signal.at,
            recurring=False,
            previous_id=previous,
        )
        session.add(incident)
        await session.flush()
        await _event(session, incident, "opened", signal.at, dedupe_key=signal.dedupe_key)
        await _said_on_open(session, incident, signal.at)
        return "opened"
    if signal.dedupe_key is None:
        # A state still true: what is said of it, kept up to date.
        incident.detail = signal.detail or incident.detail
        return None
    if not await _event(session, incident, "occurred", signal.at, dedupe_key=signal.dedupe_key):
        return None
    incident.occurrences += 1
    incident.last_seen_at = max(incident.last_seen_at, signal.at)
    incident.technical_id = signal.technical_id or incident.technical_id
    incident.detail = signal.detail or incident.detail
    await _recurring(session, incident, signal.at)
    return "occurred"


async def _recurring(session: AsyncSession, incident: Incident, at: datetime) -> None:
    if incident.recurring:
        return
    seen = await session.scalar(
        select(func.count()).where(
            IncidentEvent.incident_id == incident.id,
            IncidentEvent.kind.in_(("opened", "occurred")),
            IncidentEvent.at >= at - RECURRING_WITHIN,
        )
    )
    if int(seen or 0) < RECURRING_AFTER:
        return
    was = incident.severity
    incident.recurring = True
    incident.severity = _raised(was)
    await _event(
        session,
        incident,
        "recurring",
        at,
        detail={"severity_before": was, "severity_after": incident.severity},
    )
    await _notify(
        session,
        "repeated_errors",
        severity=incident.severity,
        at=at,
        dedupe_key=f"repeated_errors:{incident.id}",
        workspace_id=incident.for_workspace_id,
        incident_id=incident.id,
        detail={"number": incident.number, "category": incident.category, **incident.detail},
    )
    if incident.severity == "critical" and was != "critical":
        await _said_on_open(session, incident, at)


async def clear(session: AsyncSession, fingerprint: str, at: datetime, why: str) -> bool:
    """The problem went: its open incident resolved by LEKA — unless it was
    seen again after."""
    incident = await _open(session, fingerprint)
    if incident is None or at < incident.last_seen_at:
        return False
    incident.status = "resolved"
    incident.resolved_at = at
    await _event(session, incident, "auto_resolved", at, detail={"why": why})
    return True


# ── What the watch reads ─────────────────────────────────────────────────────


async def _watermark(session: AsyncSession, source: str, default: datetime) -> datetime:
    said = await session.scalar(
        select(ActivityWatermark.read_to).where(ActivityWatermark.source == source)
    )
    return said or default


async def _advance(session: AsyncSession, source: str, to: datetime) -> None:
    await session.execute(
        insert(ActivityWatermark)
        .values(id=uuid.uuid4(), source=source, read_to=to)
        .on_conflict_do_update(constraint="uq_activity_watermarks_source", set_={"read_to": to})
    )


def _ref(ref: str | None, prefix: str) -> str | None:
    return ref.removeprefix(prefix) if ref and ref.startswith(prefix) else None


async def _from_activity(
    session: AsyncSession, now: datetime
) -> tuple[list[Signal], list[tuple[str, datetime, str]]]:
    since = await _watermark(session, "incidents.activity", now - timedelta(days=1)) - OVERLAP
    events = (
        await session.scalars(
            select(ActivityEvent)
            .where(
                ActivityEvent.kind.in_(ACTIVITY_KINDS),
                ActivityEvent.at >= since,
                _real(ActivityEvent.for_workspace_id),
            )
            .order_by(ActivityEvent.at)
        )
    ).all()
    runs: dict[str, SyncRun] = {}
    sync_ids = [_ref(e.ref, "sync_run:") for e in events if e.kind == "sync.failed"]
    ids = [uuid.UUID(i) for i in sync_ids if i]
    if ids:
        runs = {
            str(r.id): r
            for r in (await session.scalars(select(SyncRun).where(SyncRun.id.in_(ids))))
        }
    sources = await _sources({r.source_id for r in runs.values()}, session)
    signals: list[Signal] = []
    clears: list[tuple[str, datetime, str]] = []
    for e in events:
        ws = e.for_workspace_id
        key = f"activity:{e.id}"
        if e.kind == "intention.failed" and (intention := _ref(e.ref, "intention:")):
            signals.append(
                Signal(
                    "intention_failed",
                    f"intention_failed:{intention}",
                    ws,
                    "medium",
                    e.at,
                    intention,
                    {"intention_id": intention},
                    key,
                )
            )
        elif e.kind == "intention.completed" and (intention := _ref(e.ref, "intention:")):
            clears.append((f"intention_failed:{intention}", e.at, "intention_completed"))
        elif e.kind in ("agent_run.failed", "agent_run.succeeded"):
            agent = str(e.properties.get("agent") or "")
            if not agent or ws is None:
                continue
            fingerprint = f"agent_failed:{ws}:{agent}"
            if e.kind == "agent_run.succeeded":
                clears.append((fingerprint, e.at, "agent_succeeded"))
                continue
            run = _ref(e.ref, "agent_run:")
            signals.append(
                Signal(
                    "agent_failed",
                    fingerprint,
                    ws,
                    "medium",
                    e.at,
                    run,
                    {"agent": agent, "agent_run_id": run},
                    key,
                )
            )
        elif e.kind == "sync.failed":
            run_id = _ref(e.ref, "sync_run:")
            found = runs.get(run_id or "")
            if found is None:
                continue
            source = sources.get(found.source_id)
            diagnostic = diagnostic_of(found.error)
            signals.append(
                Signal(
                    "sync_failed",
                    f"sync_failed:{found.source_id}",
                    ws,
                    "medium",
                    e.at,
                    str(found.source_id),
                    {
                        "source_id": str(found.source_id),
                        "source": source.name if source else None,
                        "kind": str(source.kind) if source else None,
                        "code": diagnostic.code if diagnostic else None,
                        "message": diagnostic.message if diagnostic else None,
                    },
                    key,
                )
            )
    await _advance(session, "incidents.activity", max((e.at for e in events), default=now))
    return signals, clears


async def _sources(ids: set[uuid.UUID], session: AsyncSession) -> dict[uuid.UUID, Source]:
    if not ids:
        return {}
    return {s.id: s for s in await session.scalars(select(Source).where(Source.id.in_(ids)))}


async def _payments(session: AsyncSession, now: datetime) -> list[Signal]:
    since = await _watermark(session, "incidents.payments", now - timedelta(days=1)) - OVERLAP
    failed = (
        await session.scalars(
            select(BillingPayment)
            .where(
                BillingPayment.outcome == "failed",
                BillingPayment.at >= since,
                _real(BillingPayment.workspace_id),
            )
            .order_by(BillingPayment.at)
        )
    ).all()
    await _advance(session, "incidents.payments", max((p.at for p in failed), default=now))
    return [
        Signal(
            "payment_failed",
            f"payment_failed:{p.stripe_invoice_id or p.reference}",
            p.workspace_id,
            "high",
            p.at,
            p.stripe_invoice_id,
            {
                "invoice": p.stripe_invoice_id,
                "amount": round(p.amount / 100, 2),
                "currency": p.currency,
                "attempt": p.attempt,
            },
            f"payment:{p.id}",
        )
        for p in failed
    ]


async def _states(session: AsyncSession, now: datetime) -> tuple[list[Signal], set[str], set[str]]:
    """The problems that hold now, and the fingerprints of the categories
    judged whole (integration, credits, platform): an open one not among
    them went."""
    signals: list[Signal] = []
    judged: set[str] = {"integration_disconnected", "credits"}
    failing = (
        await session.scalars(
            select(Source).where(
                Source.status != SourceStatus.DISABLED,
                or_(
                    Source.status == SourceStatus.ERROR,
                    Source.health_status == HealthStatus.UNHEALTHY,
                ),
                _real(Source.workspace_id),
            )
        )
    ).all()
    for source in failing:
        diagnostic = diagnostic_of(source.last_error)
        signals.append(
            Signal(
                "integration_disconnected",
                f"integration:{source.id}",
                source.workspace_id,
                "high",
                source.last_health_check_at or now,
                str(source.id),
                {
                    "source_id": str(source.id),
                    "source": source.name,
                    "kind": str(source.kind),
                    "code": diagnostic.code if diagnostic else None,
                    "message": diagnostic.message if diagnostic else None,
                },
            )
        )
    # Credits: those who consumed lately, this month.
    consuming = (
        await session.scalars(
            select(ActivityEvent.for_workspace_id)
            .where(
                ActivityEvent.kind == "credits.consumed",
                ActivityEvent.at >= now - timedelta(days=35),
                ActivityEvent.for_workspace_id.is_not(None),
                _real(ActivityEvent.for_workspace_id),
            )
            .distinct()
        )
    ).all()
    for workspace_id in consuming:
        if workspace_id is None:
            continue
        try:
            month = await credits_of(session, workspace_id, now)
        except Exception:
            logger.warning("incident_credits_unreadable", workspace=str(workspace_id))
            continue
        said: dict[str, object] = {
            "period": month.period,
            "used": month.used,
            "allowance": month.allowance,
        }
        if month.state == "exhausted":
            signals.append(
                Signal(
                    "credits",
                    f"credits:{workspace_id}:{month.period}",
                    workspace_id,
                    "high",
                    now,
                    month.period,
                    said,
                )
            )
        elif month.state == "warning":
            await _notify(
                session,
                "capacity_near_limit",
                severity="medium",
                at=now,
                dedupe_key=f"capacity:{workspace_id}:{month.period}",
                workspace_id=workspace_id,
                detail=said,
            )
    firing = await firing_now()
    if firing is not None:
        judged.add("platform")
        for active in firing:
            rule = active.rule
            signals.append(
                Signal(
                    "platform",
                    f"platform:{rule.name}",
                    None,
                    "critical" if rule.severity == "critical" else "medium",
                    active.since,
                    rule.name,
                    {"rule": rule.name, "why": active.why},
                )
            )
    holding = {s.fingerprint for s in signals}
    return signals, judged, holding


async def _api_errors() -> list[Signal]:
    kept = await drain_api_errors()
    signals = []
    for said in kept or []:
        try:
            at = datetime.fromisoformat(str(said["at"]))
            workspace = uuid.UUID(str(said["workspace_id"])) if said.get("workspace_id") else None
        except (KeyError, ValueError):
            continue
        method, route, exception = (
            str(said.get("method")),
            str(said.get("route")),
            str(said.get("exception")),
        )
        request_id = str(said.get("request_id") or "") or None
        signals.append(
            Signal(
                "api_error",
                f"api_error:{workspace or 'platform'}:{method} {route}:{exception}",
                workspace,
                "high",
                at,
                request_id,
                {"method": method, "route": route, "exception": exception},
                f"api:{request_id or uuid.uuid4()}",
            )
        )
    return signals


async def _resolved_elsewhere(session: AsyncSession, now: datetime) -> list[tuple[str, str]]:
    """Open payment and sync incidents whose problem went: the invoice paid
    or void, the source read again."""
    gone: list[tuple[str, str]] = []
    payments = (
        await session.scalars(
            select(Incident).where(
                Incident.category == "payment_failed", Incident.status.in_(OPEN_STATUSES)
            )
        )
    ).all()
    invoices = [i.technical_id for i in payments if i.technical_id]
    settled = (
        dict(
            (
                await session.execute(
                    select(BillingInvoice.stripe_invoice_id, BillingInvoice.status).where(
                        BillingInvoice.stripe_invoice_id.in_(invoices),
                        BillingInvoice.status.in_(("paid", "void")),
                    )
                )
            )
            .tuples()
            .all()
        )
        if invoices
        else {}
    )
    for incident in payments:
        if incident.technical_id in settled:
            gone.append((incident.fingerprint, f"invoice_{settled[incident.technical_id]}"))
    syncs = (
        await session.scalars(
            select(Incident).where(
                Incident.category == "sync_failed", Incident.status.in_(OPEN_STATUSES)
            )
        )
    ).all()
    for incident in syncs:
        try:
            source_id = uuid.UUID(str(incident.technical_id))
        except ValueError:
            continue
        read = await session.scalar(
            select(func.max(SyncRun.finished_at)).where(
                SyncRun.source_id == source_id,
                SyncRun.status == SyncRunOutcome.SUCCEEDED,
            )
        )
        if read is not None and read > incident.last_seen_at:
            gone.append((incident.fingerprint, "read_again"))
    return gone


async def _abnormal(session: AsyncSession, now: datetime) -> int:
    """A day's credits past three times the average day of the four weeks
    before, and past MIN_ABNORMAL: said once a day."""
    spent_credits = cast(ActivityEvent.properties["credits"].astext, Float)
    day = now - timedelta(days=1)
    rows = (
        await session.execute(
            select(
                ActivityEvent.for_workspace_id,
                func.coalesce(func.sum(spent_credits).filter(ActivityEvent.at >= day), 0.0),
                func.coalesce(func.sum(spent_credits).filter(ActivityEvent.at < day), 0.0),
            )
            .where(
                ActivityEvent.kind == "credits.consumed",
                ActivityEvent.at >= day - timedelta(days=28),
                ActivityEvent.for_workspace_id.is_not(None),
                _real(ActivityEvent.for_workspace_id),
            )
            .group_by(ActivityEvent.for_workspace_id)
        )
    ).tuples()
    told = 0
    for workspace_id, last_day, before in rows:
        usual = float(before) / 28
        spent = float(last_day)
        if spent >= MIN_ABNORMAL and spent > ABNORMAL_TIMES * usual:
            told += await _notify(
                session,
                "abnormal_consumption",
                severity="medium",
                at=now,
                dedupe_key=f"consumption:{workspace_id}:{now.date().isoformat()}",
                workspace_id=workspace_id,
                detail={
                    "credits_24h": round(spent, 2),
                    "usual_day": round(usual, 2),
                },
            )
    return told


async def watch(*, now: datetime | None = None) -> dict[str, int]:
    """One pass: what happened since the last, what holds now, what went."""
    moment = now or datetime.now(UTC)
    done: dict[str, int] = defaultdict(int)
    with system_scope():
        async with session_factory() as session:
            signals, clears = await _from_activity(session, moment)
            signals += await _payments(session, moment)
            states, judged, holding = await _states(session, moment)
            signals += states
            signals += await _api_errors()
            for signal in sorted(signals, key=lambda s: s.at):
                said = await apply(session, signal)
                if said:
                    done[said] += 1
            for fingerprint, at, why in clears:
                done["resolved"] += await clear(session, fingerprint, at, why)
            # What was judged whole and no longer holds.
            for incident in (
                await session.scalars(
                    select(Incident).where(
                        Incident.category.in_(judged),
                        Incident.status.in_(OPEN_STATUSES),
                        Incident.fingerprint.not_in(holding)
                        if holding
                        else Incident.id.is_not(None),
                    )
                )
            ).all():
                done["resolved"] += await clear(
                    session, incident.fingerprint, moment, f"{incident.category}_cleared"
                )
            for fingerprint, why in await _resolved_elsewhere(session, moment):
                done["resolved"] += await clear(session, fingerprint, moment, why)
            done["notified"] += await _abnormal(session, moment)
            await session.execute(
                delete(Incident).where(
                    Incident.status.in_(("resolved", "closed")),
                    Incident.last_seen_at < moment - INCIDENTS_KEPT,
                )
            )
            await session.execute(
                delete(AdminNotification).where(AdminNotification.at < moment - NOTIFICATIONS_KEPT)
            )
            await session.commit()
    logger.info("incidents_watched", **done)
    return dict(done)


def run_watch() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(watch())


# ── Reads ────────────────────────────────────────────────────────────────────


def incidents_query(
    *,
    status: Sequence[str] = (),
    severity: str | None = None,
    category: str | None = None,
    recurring: bool | None = None,
    organisation_id: uuid.UUID | None = None,
    organisation: str | None = None,
    assignee_id: uuid.UUID | None = None,
    unassigned: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
    number: int | None = None,
) -> Select[tuple[Incident]]:
    statement = select(Incident)
    if status:
        statement = statement.where(Incident.status.in_(status))
    if severity:
        statement = statement.where(Incident.severity == severity)
    if category:
        statement = statement.where(Incident.category == category)
    if recurring is not None:
        statement = statement.where(Incident.recurring.is_(recurring))
    if organisation_id:
        statement = statement.where(Incident.for_workspace_id == organisation_id)
    if organisation and organisation.strip():
        pattern = _like(organisation)
        statement = statement.where(
            Incident.for_workspace_id.in_(
                select(Workspace.id).where(
                    or_(Workspace.name.ilike(pattern), Workspace.slug.ilike(pattern))
                )
            )
        )
    if assignee_id:
        statement = statement.where(Incident.assignee_id == assignee_id)
    if unassigned:
        statement = statement.where(Incident.assignee_id.is_(None))
    if since:
        statement = statement.where(Incident.last_seen_at >= since)
    if until:
        statement = statement.where(Incident.last_seen_at < until)
    if number is not None:
        statement = statement.where(Incident.number == number)
    return statement


async def _assignees(
    session: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, IncidentAssignee]:
    if not ids:
        return {}
    return {
        a.id: IncidentAssignee(id=a.id, name=a.name, email=a.email)
        for a in await session.scalars(select(AdminAccount).where(AdminAccount.id.in_(ids)))
    }


def _organisation(
    names: dict[uuid.UUID, str], workspace_id: uuid.UUID | None
) -> OrganisationRef | None:
    return (
        OrganisationRef(id=workspace_id, name=names.get(workspace_id, "")) if workspace_id else None
    )


async def incident_rows(session: AsyncSession, incidents: Sequence[Incident]) -> list[IncidentRow]:
    names = await _organisation_names(session, (i.for_workspace_id for i in incidents))
    people = await _assignees(session, {i.assignee_id for i in incidents if i.assignee_id})
    return [
        IncidentRow(
            id=i.id,
            number=i.number,
            organisation=_organisation(names, i.for_workspace_id),
            category=i.category,
            severity=i.severity,
            status=i.status,
            technical_id=i.technical_id,
            detail=dict(i.detail),
            occurrences=i.occurrences,
            recurring=i.recurring,
            first_seen_at=i.first_seen_at,
            last_seen_at=i.last_seen_at,
            assignee=people.get(i.assignee_id) if i.assignee_id else None,
            resolved_at=i.resolved_at,
            closed_at=i.closed_at,
        )
        for i in incidents
    ]


async def incident_detail(session: AsyncSession, incident_id: uuid.UUID) -> IncidentRecord | None:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        return None
    [row] = await incident_rows(session, [incident])
    events = (
        await session.scalars(
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.at.desc(), IncidentEvent.created_at.desc())
        )
    ).all()
    previous = await session.get(Incident, incident.previous_id) if incident.previous_id else None
    return IncidentRecord(
        incident=row,
        previous_number=previous.number if previous else None,
        previous_id=incident.previous_id,
        history=[
            IncidentEventRow(
                id=e.id,
                kind=e.kind,
                at=e.at,
                by=e.admin_email,
                detail=dict(e.detail),
            )
            for e in events
        ],
    )


async def summary(session: AsyncSession) -> IncidentSummary:
    open_ = Incident.status.in_(OPEN_STATUSES)
    by = (
        await session.execute(
            select(Incident.severity, Incident.category, Incident.status, func.count())
            .where(open_)
            .group_by(Incident.severity, Incident.category, Incident.status)
        )
    ).tuples()
    severity: dict[str, int] = defaultdict(int)
    category: dict[str, int] = defaultdict(int)
    status: dict[str, int] = defaultdict(int)
    for sev, cat, st, n in by:
        severity[sev] += int(n)
        category[cat] += int(n)
        status[st] += int(n)
    unassigned = await session.scalar(
        select(func.count()).where(open_, Incident.assignee_id.is_(None))
    )
    recurring = await session.scalar(select(func.count()).where(open_, Incident.recurring))
    return IncidentSummary(
        open=sum(status.values()),
        by_status={s: status.get(s, 0) for s in OPEN_STATUSES},
        by_severity={s: severity.get(s, 0) for s in SEVERITIES},
        by_category=dict(sorted(category.items(), key=lambda item: -item[1])),
        unassigned=int(unassigned or 0),
        recurring=int(recurring or 0),
    )


async def assignees(session: AsyncSession) -> list[IncidentAssignee]:
    """Who an incident may be given to: the team, active."""
    return [
        IncidentAssignee(id=a.id, name=a.name, email=a.email)
        for a in await session.scalars(
            select(AdminAccount).where(AdminAccount.status == "active").order_by(AdminAccount.name)
        )
    ]


async def change_incident(
    session: AsyncSession,
    incident_id: uuid.UUID,
    change: IncidentChange,
    *,
    by_id: uuid.UUID,
    by_email: str,
    now: datetime,
) -> Incident:
    """Taken up, resolved, closed or taken up again, given to someone, a
    note — each kept in its history, in that order (a microsecond apart, so
    the history reads them as they were done). Raises IncidentError."""
    incident = await session.get(Incident, incident_id, with_for_update=True)
    if incident is None:
        raise IncidentError("not_found", "No incident with this id.")
    if "assignee_id" in change.model_fields_set:
        target = change.assignee_id
        if target is not None:
            person = await session.get(AdminAccount, target)
            if person is None or person.status != "active":
                raise IncidentError("assignee", "An incident goes to an active admin.")
        if incident.assignee_id != target:
            incident.assignee_id = target
            await _event(
                session,
                incident,
                "assigned",
                now + timedelta(microseconds=0),
                admin_id=by_id,
                admin_email=by_email,
                detail={"assignee_id": str(target) if target else None},
            )
    if change.status and change.status != incident.status:
        if change.status not in TRANSITIONS[incident.status]:
            raise IncidentError(
                "transition", f"An incident {incident.status} cannot become {change.status}."
            )
        if change.status in OPEN_STATUSES and await session.scalar(
            select(Incident.id).where(
                Incident.fingerprint == incident.fingerprint,
                Incident.status.in_(OPEN_STATUSES),
                Incident.id != incident.id,
            )
        ):
            raise IncidentError("reopened", "A newer incident is open for the same problem.")
        before = incident.status
        incident.status = change.status
        if change.status == "resolved":
            incident.resolved_at = now
        elif change.status == "closed":
            incident.closed_at = now
            incident.resolved_at = incident.resolved_at or now
        elif before == "resolved":
            incident.resolved_at = None
        await _event(
            session,
            incident,
            "status",
            now + timedelta(microseconds=1),
            admin_id=by_id,
            admin_email=by_email,
            detail={"from": before, "to": change.status},
        )
    if change.note:
        await _event(
            session,
            incident,
            "note",
            now + timedelta(microseconds=2),
            admin_id=by_id,
            admin_email=by_email,
            detail={"note": change.note},
        )
    await session.flush()
    return incident


# ── The team's notifications ─────────────────────────────────────────────────


def notifications_query(
    *,
    admin_id: uuid.UUID,
    unread: bool = False,
    kind: str | None = None,
    organisation_id: uuid.UUID | None = None,
) -> Select[tuple[AdminNotification]]:
    statement = select(AdminNotification)
    if unread:
        statement = statement.where(
            ~select(AdminNotificationRead.id)
            .where(
                AdminNotificationRead.notification_id == AdminNotification.id,
                AdminNotificationRead.admin_id == admin_id,
            )
            .exists()
        )
    if kind:
        statement = statement.where(AdminNotification.kind == kind)
    if organisation_id:
        statement = statement.where(AdminNotification.for_workspace_id == organisation_id)
    return statement


async def notification_rows(
    session: AsyncSession, notifications: Sequence[AdminNotification], *, admin_id: uuid.UUID
) -> list[AdminNotificationRow]:
    names = await _organisation_names(session, (n.for_workspace_id for n in notifications))
    ids = [n.id for n in notifications]
    read = (
        dict(
            (
                await session.execute(
                    select(
                        AdminNotificationRead.notification_id, AdminNotificationRead.read_at
                    ).where(
                        AdminNotificationRead.admin_id == admin_id,
                        AdminNotificationRead.notification_id.in_(ids),
                    )
                )
            )
            .tuples()
            .all()
        )
        if ids
        else {}
    )
    numbers = (
        dict(
            (
                await session.execute(
                    select(Incident.id, Incident.number).where(
                        Incident.id.in_([n.incident_id for n in notifications if n.incident_id])
                    )
                )
            )
            .tuples()
            .all()
        )
        if any(n.incident_id for n in notifications)
        else {}
    )
    return [
        AdminNotificationRow(
            id=n.id,
            kind=n.kind,
            severity=n.severity,
            at=n.at,
            organisation=_organisation(names, n.for_workspace_id),
            incident_id=n.incident_id,
            incident_number=numbers.get(n.incident_id) if n.incident_id else None,
            detail=dict(n.detail),
            read_at=read.get(n.id),
        )
        for n in notifications
    ]


async def unread_count(session: AsyncSession, admin_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(
                notifications_query(admin_id=admin_id, unread=True).subquery()
            )
        )
        or 0
    )


async def mark_read(
    session: AsyncSession,
    admin_id: uuid.UUID,
    *,
    ids: Sequence[uuid.UUID] = (),
    every: bool = False,
    now: datetime,
) -> int:
    """Read by this admin: these, or every one not read yet. How many."""
    # Only notifications that exist: an id that does not is left out.
    chosen = notifications_query(admin_id=admin_id, unread=True).with_only_columns(
        AdminNotification.id
    )
    if not every:
        chosen = chosen.where(AdminNotification.id.in_(list(ids)))
    targets = (await session.scalars(chosen)).all() if every or ids else []
    done = 0
    for notification_id in targets:
        written = await session.scalar(
            insert(AdminNotificationRead)
            .values(
                id=uuid.uuid4(), notification_id=notification_id, admin_id=admin_id, read_at=now
            )
            .on_conflict_do_nothing(constraint="uq_admin_notification_reads")
            .returning(AdminNotificationRead.id)
        )
        done += written is not None
    return done


__all__ = [
    "IncidentError",
    "Signal",
    "apply",
    "assignees",
    "change_incident",
    "clear",
    "incident_detail",
    "incident_rows",
    "incidents_query",
    "mark_read",
    "notification_rows",
    "notifications_query",
    "run_watch",
    "summary",
    "unread_count",
    "watch",
]
