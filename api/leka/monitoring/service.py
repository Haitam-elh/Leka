"""Watching the environment (LEKA-442): the Digital Twin's states read again
after the sources are, and an alert kept for what is in trouble — for the
workspaces whose plan watches proactively.

    entitled()    what a workspace's plan includes: proactive watching, the
                  ways it is told — the catalogue's word (billing)
    judge()       the states now against the alerts open — pure:
                    unavailable, degraded        opened, or made worse or
                                                 milder, never twice
                    a source failing             opened
                    well, a fresh signal saying  resolved — the signal said
                      so (measured or declared)
                    stale, unknown, not covered  kept open, unverified:
                                                 silence resolves nothing
                    a thing gone from the model  closed, said why
    sweep()       judged and kept, per workspace — and those just opened
                  told by e-mail when the plan includes it

What is not included is never simulated: a Free workspace's states are seen
on its screens; no alert is opened for it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing import Monitoring, catalogue
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import plan_of
from leka.identity import EmailMessage, User, build_email_sender, email_language
from leka.ingestion import EnrichmentRepository, SourceSeen, TwinState, twin_now
from leka.monitoring.models import MonitoringAlert
from leka.monitoring.repository import AlertRepository
from leka.platform import Membership, Role, Workspace

logger = structlog.get_logger(__name__)

ALERTING = {"unavailable": "high", "degraded": "medium"}
# What a fresh signal must be to say a trouble ended: a tool's measure or a
# provider's word — never a deduction, never silence.
VERIFYING = frozenset({"measured", "declared"})


# ── what a plan includes ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Entitlement:
    plan: str
    monitoring: Monitoring
    # The cheapest plans that include what this one does not.
    alerts_from: str | None
    email_from: str | None


def entitlement_of(plan: str) -> Entitlement:
    sold = catalogue()
    included = next((p.monitoring for p in sold.plans if p.key == plan), None)
    found = included or Monitoring(proactive=False)
    return Entitlement(
        plan=plan,
        monitoring=found,
        alerts_from=next((p.key for p in sold.plans if p.monitoring.proactive), None),
        email_from=next((p.key for p in sold.plans if "email" in p.monitoring.alerts), None),
    )


async def entitled(session: AsyncSession, workspace_id: uuid.UUID) -> Entitlement:
    return entitlement_of((await plan_of(session, workspace_id)).name)


# ── judging ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Seen:
    """A thing or a source, as the sweep sees it now."""

    subject_type: str
    subject_id: uuid.UUID
    name: str
    state: str  # a twin state; a source: read, error…
    basis: str = "none"
    reason: str = ""
    fresh: bool = True
    certainty: str = "confirmed"
    signal: tuple[str, ...] = ()
    incident: Mapping[str, object] | None = None


@dataclass(frozen=True)
class Open:
    """An alert open now."""

    id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    family: str
    kind: str
    severity: str
    certainty: str


@dataclass
class Judged:
    opened: list[dict[str, object]] = field(default_factory=list)
    updated: list[tuple[uuid.UUID, dict[str, object]]] = field(default_factory=list)
    resolved: list[tuple[uuid.UUID, dict[str, object]]] = field(default_factory=list)
    closed: list[tuple[uuid.UUID, dict[str, object]]] = field(default_factory=list)


def _trouble(seen: Seen) -> tuple[str, str, str] | None:
    """(family, kind, severity) of what is wrong with it — None when well."""
    if seen.subject_type == "source":
        return ("source", "source_failing", "medium") if seen.state == "error" else None
    if seen.state in ALERTING:
        return "health", seen.state, ALERTING[seen.state]
    return None


def _detail(seen: Seen) -> dict[str, object]:
    return {
        "reason": seen.reason,
        "basis": seen.basis,
        "signal": list(seen.signal),
        "incident": dict(seen.incident) if seen.incident else None,
    }


def judge(seen: Sequence[Seen], alerts: Sequence[Open], now: datetime) -> Judged:
    """The states now against the alerts open: what to open, update,
    resolve or close. Pure."""
    out = Judged()
    by_subject = {(s.subject_type, s.subject_id): s for s in seen}
    held = {(a.subject_id, a.family): a for a in alerts}
    for one in seen:
        trouble = _trouble(one)
        if trouble is None:
            continue
        family, kind, severity = trouble
        certainty = one.certainty if one.fresh else "unverified"
        existing = held.get((one.subject_id, family))
        if existing is None:
            out.opened.append(
                {
                    "subject_type": one.subject_type,
                    "subject_id": one.subject_id,
                    "subject_name": one.name,
                    "family": family,
                    "kind": kind,
                    "severity": severity,
                    "certainty": certainty,
                    "opened_at": now,
                    "last_seen_at": now,
                    "detail": _detail(one),
                }
            )
        else:
            out.updated.append(
                (
                    existing.id,
                    {
                        "kind": kind,
                        "severity": severity,
                        "certainty": certainty,
                        "last_seen_at": now,
                        "detail": _detail(one),
                    },
                )
            )
    for alert in alerts:
        now_seen = by_subject.get((alert.subject_type, alert.subject_id))
        if now_seen is None:
            out.closed.append((alert.id, {"reason": "subject_gone", "at": now.isoformat()}))
            continue
        if _trouble(now_seen) is not None:
            continue
        well = (
            now_seen.state == "read"
            if alert.subject_type == "source"
            else (
                now_seen.state == "operational" and now_seen.fresh and now_seen.basis in VERIFYING
            )
        )
        if well:
            out.resolved.append(
                (
                    alert.id,
                    {
                        "reason": now_seen.reason or "read",
                        "basis": now_seen.basis,
                        "signal": list(now_seen.signal),
                        "at": now.isoformat(),
                    },
                )
            )
        elif alert.certainty != "unverified":
            # Silence, staleness, a deduction: it may be over — nothing says
            # so. Kept open, unverified.
            out.updated.append((alert.id, {"certainty": "unverified"}))
    return out


def seen_of(
    states: Mapping[uuid.UUID, TwinState | None],
    names: Mapping[uuid.UUID, str],
    sources: Sequence[SourceSeen],
    now: datetime,
) -> list[Seen]:
    out: list[Seen] = []
    for thing_id, found in states.items():
        if found is None:
            continue
        incident = found.incident
        out.append(
            Seen(
                "entity",
                thing_id,
                names.get(thing_id, ""),
                found.state,
                basis=found.basis,
                reason=found.reason,
                fresh=found.fresh,
                certainty=found.certainty,
                signal=found.signal,
                incident={"key": incident.key, "name": incident.name, "severity": incident.severity}
                if incident is not None
                else None,
            )
        )
    for source in sources:
        if not source.connected:
            continue
        out.append(
            Seen(
                "source",
                source.id,
                source.name,
                source.state(now),
                basis="measured",
                reason=source.error or "",
                signal=(source.name,),
            )
        )
    return out


# ── the sweep ────────────────────────────────────────────────────────────────


def run_monitoring_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(sweep())


async def sweep(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace whose plan watches proactively, judged and kept.
    One that fails is logged; the others are watched all the same."""
    moment = now or datetime.now(UTC)
    with system_scope():
        async with session_factory() as session:
            workspaces = list((await session.scalars(select(Workspace.id))).all())
    opened = 0
    for workspace_id in workspaces:
        try:
            opened += await watch(workspace_id, moment)
        except Exception:
            logger.exception("monitoring_sweep_failed", workspace=str(workspace_id))
    return {"workspaces": len(workspaces), "opened": opened}


async def watch(workspace_id: uuid.UUID, now: datetime) -> int:
    """One workspace: its states judged, its alerts kept, those just opened
    told. Nothing for a plan that does not watch proactively."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            entitlement = await entitled(session, workspace_id)
            if not entitlement.monitoring.proactive:
                return 0
            things, states, sources = await twin_now(
                EnrichmentRepository(session, workspace_id), now
            )
            alerts = AlertRepository(session, workspace_id)
            rows = list(await alerts.open())
            judged = judge(
                seen_of(states, {i: t.name for i, t in things.items()}, sources, now),
                [
                    Open(
                        r.id,
                        r.subject_type,
                        r.subject_id,
                        r.family,
                        r.kind,
                        r.severity,
                        r.certainty,
                    )
                    for r in rows
                ],
                now,
            )
            by_id = {r.id: r for r in rows}
            fresh: list[MonitoringAlert] = []
            for values in judged.opened:
                alert = MonitoringAlert(workspace_id=workspace_id, id=uuid.uuid4(), **values)
                alerts.add(alert)
                fresh.append(alert)
            for alert_id, values in judged.updated:
                for key, value in values.items():
                    setattr(by_id[alert_id], key, value)
            for alert_id, resolution in judged.resolved:
                by_id[alert_id].status = "resolved"
                by_id[alert_id].resolved_at = now
                by_id[alert_id].resolution = resolution
            for alert_id, resolution in judged.closed:
                by_id[alert_id].status = "closed"
                by_id[alert_id].resolved_at = now
                by_id[alert_id].resolution = resolution
            await session.commit()
            if fresh and "email" in entitlement.monitoring.alerts:
                await _tell(session, workspace_id, fresh, now)
            return len(fresh)


# ── telling ──────────────────────────────────────────────────────────────────

_WORDS: dict[str, dict[str, str]] = {
    "fr": {
        "subject": "LEKA — {count} {alerts} sur {name}",
        "one": "alerte",
        "many": "alertes",
        "nameless": "votre espace",
        "intro": "LEKA a ouvert de nouvelles alertes sur votre environnement :",
        "unavailable": "indisponible",
        "degraded": "dégradé",
        "source_failing": "source en échec",
        "confirmed": "confirmé",
        "suspected": "soupçonné",
        "unverified": "non vérifié",
        "end": "Le détail, ce qui l'étaie et l'intention à lancer : Mon environnement, dans LEKA.",
    },
    "en": {
        "subject": "LEKA — {count} {alerts} on {name}",
        "one": "alert",
        "many": "alerts",
        "nameless": "your workspace",
        "intro": "LEKA opened new alerts on your environment:",
        "unavailable": "unavailable",
        "degraded": "degraded",
        "source_failing": "source failing",
        "confirmed": "confirmed",
        "suspected": "suspected",
        "unverified": "unverified",
        "end": (
            "The detail, what supports it and the intention to start: Mon environnement, in LEKA."
        ),
    },
}


def message(alerts: Sequence[MonitoringAlert], name: str | None, language: str) -> EmailMessage:
    words = _WORDS.get(language) or _WORDS["en"]
    lines = [
        f"- {a.subject_name}: {words[a.kind]} ({words[a.certainty]})"
        for a in sorted(alerts, key=lambda a: (a.severity != "high", a.subject_name))
    ]
    subject = words["subject"].format(
        count=len(alerts),
        alerts=words["one"] if len(alerts) == 1 else words["many"],
        name=name or words["nameless"],
    )
    body = "\n".join([words["intro"], *lines, "", words["end"]])
    return EmailMessage(to="", subject=subject[:200], body=body, language=language)


async def _tell(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    alerts: Sequence[MonitoringAlert],
    now: datetime,
) -> None:
    """Its owners and admins, told once of what just opened — each in their
    language, else the workspace's."""
    to = (
        await session.execute(
            select(User.email, User.language)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.workspace_id == workspace_id,
                Membership.role.in_([Role.OWNER, Role.ADMIN]),
            )
        )
    ).all()
    workspace = await session.get(Workspace, workspace_id)
    name = workspace.name if workspace is not None else None
    sender = build_email_sender()
    for address, chosen in sorted(set(to)):
        language = email_language(
            chosen, workspace=workspace.default_language if workspace else None
        )
        try:
            await sender.send(replace(message(alerts, name, language), to=address))
        except Exception:
            logger.warning(
                "monitoring_alert_email_failed", workspace=str(workspace_id), exc_info=True
            )
    for alert in alerts:
        alert.notified = {**alert.notified, "email": now.isoformat()}
    await session.commit()
