"""The alerts a person sets on Mon environnement (LEKA-477), on top of the
watch (service.py): « tell me when this goes wrong ».

    watchable()   what a rule may be set on: a thing whose state a source
                  says, with a known freshness — its troubles unavailable,
                  degraded — or a connected source — failing. Nothing else
                  is offered: no threshold on a metric no source collects.
    channels()    every way LEKA may tell, and where each stands: in_app and
                  e-mail are integrated — e-mail said operational only once
                  a delivery went; SMS, WhatsApp, Slack, Teams, Discord said
                  unavailable — and what the plan does not include, said so
    create(), change(), remove()
                  checked here, never trusted from a screen: the subject
                  watched, its conditions seen there, its channels
                  integrated and in the plan, its recipients members; on
                  more than the plan's `alert_rules` — refused, the plan
                  that allows more named (PlanLimitError)
    test()        each of its channels tried now, each telling kept
    deliver()     after each sweep: an alert open on its subject, for one
                  of its troubles, confirmed or suspected — never on stale
                  data — open for its confirmation delay: told once per
                  rule, alert, channel and recipient; again every
                  `repeat_hours` while open and nobody took it in hand.
                  Each telling kept, sent or failed — a failure said.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing.limits import limit_of, room_for_alert_rule
from leka.identity import EmailMessage, User, build_email_sender, email_language
from leka.ingestion import EnrichmentRepository, twin_now
from leka.monitoring import webhooks
from leka.monitoring.models import (
    CHANNELS,
    WEBHOOK_CHANNELS,
    AlertDelivery,
    AlertRule,
    MonitoringAlert,
)
from leka.monitoring.service import entitled
from leka.platform import Membership, Workspace

logger = structlog.get_logger(__name__)

# The channels LEKA really delivers through — the webhooks once connected
# (LEKA-496); SMS and WhatsApp never offered.
INTEGRATED = ("in_app", "email", *WEBHOOK_CHANNELS)
# Told in LEKA itself: the alert is on its screens for every member.
IN_APP = "workspace"
CONDITIONS = {"entity": ("unavailable", "degraded"), "source": ("source_failing",)}


class RuleRefusedError(Exception):
    """A rule that cannot be kept as asked: why, in a word."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


# A telling already made: rule, alert, channel, recipient, round.
Told = tuple[uuid.UUID, uuid.UUID | None, str, str, int]


@dataclass(frozen=True)
class Watchable:
    subject_type: str
    subject_id: uuid.UUID
    name: str
    kind: str  # service, database, infra_resource, source
    conditions: tuple[str, ...]
    state: str
    fresh: bool
    observed_at: datetime | None


@dataclass(frozen=True)
class Channel:
    key: str
    # operational, untested, failing, not_connected, not_in_plan, unavailable
    status: str
    # A webhook's: what it is connected to, recognisable, never usable.
    hint: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RuleSpec:
    name: str
    subject_type: str
    subject_id: uuid.UUID
    conditions: tuple[str, ...]
    severity: str
    confirm_minutes: int
    repeat_hours: int | None
    channels: tuple[str, ...]
    recipients: tuple[uuid.UUID, ...]
    enabled: bool


async def watchable(
    session: AsyncSession, workspace_id: uuid.UUID, now: datetime
) -> list[Watchable]:
    things, states, sources = await twin_now(EnrichmentRepository(session, workspace_id), now)
    out: list[Watchable] = []
    for thing_id, thing in things.items():
        state = states.get(thing_id)
        # Only where a source says its state, and when.
        if state is None or state.basis == "none" or state.observed_at is None:
            continue
        out.append(
            Watchable(
                "entity",
                thing_id,
                thing.name,
                thing.type,
                CONDITIONS["entity"],
                state.state,
                state.fresh,
                state.observed_at,
            )
        )
    for source in sources:
        if not source.connected:
            continue
        said = source.state(now)
        out.append(
            Watchable(
                "source",
                source.id,
                source.name,
                "source",
                CONDITIONS["source"],
                said,
                said != "stale",
                source.last_synced_at,
            )
        )
    return sorted(out, key=lambda w: (w.subject_type != "entity", w.name.lower()))


async def channels(session: AsyncSession, workspace_id: uuid.UUID) -> list[Channel]:
    included = set((await entitled(session, workspace_id)).monitoring.alerts)
    last = await session.scalar(
        select(AlertDelivery.status)
        .where(AlertDelivery.workspace_id == workspace_id, AlertDelivery.channel == "email")
        .order_by(AlertDelivery.at.desc())
        .limit(1)
    )
    connected = await webhooks.endpoints(session, workspace_id)
    out: list[Channel] = []
    for key in CHANNELS:
        if key not in INTEGRATED:
            status = "unavailable"
        elif key not in included:
            status = "not_in_plan"
        elif key == "in_app":
            status = "operational"
        elif key in WEBHOOK_CHANNELS:
            endpoint = connected.get(key)
            if endpoint is None:
                out.append(Channel(key, "not_connected"))
                continue
            out.append(Channel(key, endpoint.status, endpoint.hint, endpoint.last_error))
            continue
        else:
            # Operational only once a delivery went (a test, or an alert).
            status = {"sent": "operational", "failed": "failing"}.get(str(last), "untested")
        out.append(Channel(key, status))
    return out


async def quota(session: AsyncSession, workspace_id: uuid.UUID) -> tuple[int | None, int]:
    """The plan's limit (None: no limit) and the rules on now."""
    used = await session.scalar(
        select(func.count())
        .select_from(AlertRule)
        .where(AlertRule.workspace_id == workspace_id, AlertRule.enabled.is_(True))
    )
    return await limit_of(session, workspace_id, "alert_rules"), int(used or 0)


async def _members(
    session: AsyncSession, workspace_id: uuid.UUID, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str | None]]:
    """Those of them who are members here: their address, their language."""
    if not ids:
        return {}
    rows = await session.execute(
        select(User.id, User.email, User.language)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == workspace_id, User.id.in_(list(ids)))
    )
    return {row.id: (row.email, row.language) for row in rows}


async def _checked(
    session: AsyncSession, workspace_id: uuid.UUID, spec: RuleSpec, now: datetime
) -> str:
    """The subject's name — or RuleRefusedError, said why."""
    found = next(
        (
            w
            for w in await watchable(session, workspace_id, now)
            if (w.subject_type, w.subject_id) == (spec.subject_type, spec.subject_id)
        ),
        None,
    )
    if found is None:
        raise RuleRefusedError("not_watched", "LEKA does not read the state of this here.")
    if not spec.conditions or set(spec.conditions) - set(found.conditions):
        raise RuleRefusedError("condition_unavailable", "This condition is not read here.")
    usable = {
        c.key
        for c in await channels(session, workspace_id)
        if c.status in ("operational", "untested", "failing")
    }
    if not spec.channels or set(spec.channels) - usable:
        raise RuleRefusedError("channel_unavailable", "This channel is not available here.")
    if "email" in spec.channels:
        members = await _members(session, workspace_id, spec.recipients)
        if not spec.recipients or set(spec.recipients) - set(members):
            raise RuleRefusedError("not_a_member", "E-mail goes to members of this workspace.")
    return found.name


def _apply(rule: AlertRule, spec: RuleSpec, name: str) -> None:
    rule.name = spec.name
    rule.subject_type = spec.subject_type
    rule.subject_id = spec.subject_id
    rule.subject_name = name
    rule.conditions = list(dict.fromkeys(spec.conditions))
    rule.severity = spec.severity
    rule.confirm_minutes = spec.confirm_minutes
    rule.repeat_hours = spec.repeat_hours
    rule.channels = list(dict.fromkeys(spec.channels))
    rule.recipients = [str(r) for r in dict.fromkeys(spec.recipients)]
    rule.enabled = spec.enabled


async def create(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    spec: RuleSpec,
    *,
    by: uuid.UUID,
    now: datetime,
) -> AlertRule:
    name = await _checked(session, workspace_id, spec, now)
    if spec.enabled:
        await room_for_alert_rule(session, workspace_id, (await quota(session, workspace_id))[1])
    rule = AlertRule(workspace_id=workspace_id, id=uuid.uuid4(), created_by=by)
    _apply(rule, spec, name)
    session.add(rule)
    await session.commit()
    return rule


async def one(session: AsyncSession, workspace_id: uuid.UUID, rule_id: uuid.UUID) -> AlertRule:
    rule = await session.scalar(
        select(AlertRule).where(AlertRule.workspace_id == workspace_id, AlertRule.id == rule_id)
    )
    if rule is None:
        raise RuleRefusedError("not_found", "No such alert rule.")
    return rule


def spec_of(rule: AlertRule) -> RuleSpec:
    return RuleSpec(
        name=rule.name,
        subject_type=rule.subject_type,
        subject_id=rule.subject_id,
        conditions=tuple(rule.conditions),
        severity=rule.severity,
        confirm_minutes=rule.confirm_minutes,
        repeat_hours=rule.repeat_hours,
        channels=tuple(rule.channels),
        recipients=tuple(uuid.UUID(r) for r in rule.recipients),
        enabled=rule.enabled,
    )


async def change(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    rule_id: uuid.UUID,
    changes: dict[str, object],
    *,
    now: datetime,
) -> AlertRule:
    rule = await one(session, workspace_id, rule_id)
    spec = replace(spec_of(rule), **changes)  # type: ignore[arg-type]
    if spec.enabled:
        # Turned back on: one more against the plan's limit.
        if not rule.enabled:
            used = (await quota(session, workspace_id))[1]
            await room_for_alert_rule(session, workspace_id, used)
        name = await _checked(session, workspace_id, spec, now)
    else:
        # Turned off, it may stay as it was, even on what is no longer read.
        name = rule.subject_name
    _apply(rule, spec, name)
    await session.commit()
    return rule


async def remove(session: AsyncSession, workspace_id: uuid.UUID, rule_id: uuid.UUID) -> None:
    await session.delete(await one(session, workspace_id, rule_id))
    await session.commit()


async def deliveries(
    session: AsyncSession, workspace_id: uuid.UUID, rule_ids: Sequence[uuid.UUID], *, per: int = 5
) -> dict[uuid.UUID, list[AlertDelivery]]:
    """Each rule's latest tellings, the latest first."""
    out: dict[uuid.UUID, list[AlertDelivery]] = {r: [] for r in rule_ids}
    if not rule_ids:
        return out
    rows = await session.scalars(
        select(AlertDelivery)
        .where(AlertDelivery.workspace_id == workspace_id, AlertDelivery.rule_id.in_(rule_ids))
        .order_by(AlertDelivery.at.desc())
        .limit(per * len(rule_ids) * 4)
    )
    for row in rows:
        if len(out[row.rule_id]) < per:
            out[row.rule_id].append(row)
    return out


# ── telling ──────────────────────────────────────────────────────────────────

_WORDS: dict[str, dict[str, str]] = {
    "fr": {
        "subject": "LEKA · Alerte « {rule} » : {name} {kind}",
        "test_subject": "LEKA · Test de l'alerte « {rule} »",
        "body": "{name} est {kind} ({certainty}), depuis le {since}.\nGravité : {severity}.",
        "test_body": "Ceci est un test : l'alerte « {rule} » vous écrira ici.",
        "end": "Le détail et l'intention à lancer : Mon environnement, dans LEKA.",
        "unavailable": "indisponible",
        "degraded": "dégradé",
        "source_failing": "en échec",
        "confirmed": "confirmé",
        "suspected": "soupçonné",
        "unverified": "non vérifié",
        "high": "haute",
        "medium": "moyenne",
        "low": "basse",
    },
    "en": {
        "subject": "LEKA · Alert « {rule} »: {name} {kind}",
        "test_subject": "LEKA · Test of the alert « {rule} »",
        "body": "{name} is {kind} ({certainty}), since {since}.\nSeverity: {severity}.",
        "test_body": "This is a test: the alert « {rule} » will write to you here.",
        "end": "The detail and the intention to start: Mon environnement, in LEKA.",
        "unavailable": "unavailable",
        "degraded": "degraded",
        "source_failing": "failing",
        "confirmed": "confirmed",
        "suspected": "suspected",
        "unverified": "unverified",
        "high": "high",
        "medium": "medium",
        "low": "low",
    },
}


def told(rule: AlertRule, alert: MonitoringAlert | None, language: str) -> EmailMessage:
    """The e-mail of one telling — a test when there is no alert."""
    words = _WORDS.get(language) or _WORDS["en"]
    if alert is None:
        subject = words["test_subject"].format(rule=rule.name)
        body = words["test_body"].format(rule=rule.name)
    else:
        subject = words["subject"].format(
            rule=rule.name, name=alert.subject_name, kind=words[alert.kind]
        )
        body = words["body"].format(
            name=alert.subject_name,
            kind=words[alert.kind],
            certainty=words[alert.certainty],
            since=alert.opened_at.strftime("%Y-%m-%d %H:%M UTC"),
            severity=words[rule.severity],
        )
    return EmailMessage(
        to="", subject=subject[:200], body=f"{body}\n\n{words['end']}", language=language
    )


async def _send(
    session: AsyncSession,
    rule: AlertRule,
    alert: MonitoringAlert | None,
    *,
    round_: int,
    now: datetime,
    done: set[Told],
) -> list[AlertDelivery]:
    """Each of its channels, each recipient not yet told this round."""
    workspace_id = rule.workspace_id
    workspace = await session.get(Workspace, workspace_id)
    included = set((await entitled(session, workspace_id)).monitoring.alerts)
    made: list[AlertDelivery] = []

    def kept(channel: str, recipient: str, error: str | None) -> None:
        # Told already this round, for this alert: never twice.
        if alert is not None and (rule.id, alert.id, channel, recipient[:320], round_) in done:
            return
        row = AlertDelivery(
            workspace_id=workspace_id,
            rule_id=rule.id,
            alert_id=alert.id if alert is not None else None,
            channel=channel,
            recipient=recipient[:320],
            round=round_,
            status="failed" if error else "sent",
            error=error[:300] if error else None,
            at=now,
        )
        session.add(row)
        made.append(row)

    for channel in rule.channels:
        if channel not in INTEGRATED:
            continue
        if channel not in included:
            # The plan no longer includes it: said, never sent.
            kept(channel, IN_APP, "not_in_plan")
            continue
        if channel == "in_app":
            kept(channel, IN_APP, None)
            continue
        if channel in WEBHOOK_CHANNELS:
            # Its webhook (LEKA-496): one message, to where it was connected.
            endpoint = (await webhooks.endpoints(session, workspace_id)).get(channel)
            if alert is not None and (rule.id, alert.id, channel, channel, round_) in done:
                continue
            if endpoint is None:
                kept(channel, channel, "not_connected")
                continue
            language = workspace.default_language if workspace else "en"
            said = told(rule, alert, language)
            sent = await webhooks.post(endpoint, f"*{said.subject}*\n{said.body}", now=now)
            kept(channel, channel, sent.error)
            continue
        members = await _members(session, workspace_id, [uuid.UUID(r) for r in rule.recipients])
        sender = build_email_sender()
        for address, chosen in sorted(members.values()):
            if alert is not None and (rule.id, alert.id, channel, address[:320], round_) in done:
                continue
            language = email_language(
                chosen, workspace=workspace.default_language if workspace else None
            )
            try:
                await sender.send(replace(told(rule, alert, language), to=address))
            except Exception as error:
                logger.warning(
                    "alert_rule_email_failed", rule=str(rule.id), workspace=str(workspace_id)
                )
                kept(channel, address, type(error).__name__ + (f": {error}" if str(error) else ""))
            else:
                kept(channel, address, None)
    return made


async def test(
    session: AsyncSession, workspace_id: uuid.UUID, rule_id: uuid.UUID, *, now: datetime
) -> list[AlertDelivery]:
    rule = await one(session, workspace_id, rule_id)
    made = await _send(session, rule, None, round_=0, now=now, done=set())
    await session.commit()
    return made


def round_of(rule: AlertRule, alert: MonitoringAlert, now: datetime) -> int | None:
    """Which telling is due now — None: none yet (not confirmed long enough)."""
    confirm = timedelta(minutes=rule.confirm_minutes)
    age = now - alert.opened_at
    if age < confirm:
        return None
    # Taken in hand: told once, never reminded.
    if not rule.repeat_hours or alert.acknowledged_at is not None:
        return 0
    return int((age - confirm) / timedelta(hours=rule.repeat_hours))


async def deliver(session: AsyncSession, workspace_id: uuid.UUID, now: datetime) -> int:
    """After a sweep: what the rules say to tell, told — how many tellings."""
    rules = list(
        (
            await session.scalars(
                select(AlertRule).where(
                    AlertRule.workspace_id == workspace_id, AlertRule.enabled.is_(True)
                )
            )
        ).all()
    )
    if not rules:
        return 0
    alerts = list(
        (
            await session.scalars(
                select(MonitoringAlert).where(
                    MonitoringAlert.workspace_id == workspace_id, MonitoringAlert.status == "open"
                )
            )
        ).all()
    )
    if not alerts:
        return 0
    rows = await session.execute(
        select(
            AlertDelivery.rule_id,
            AlertDelivery.alert_id,
            AlertDelivery.channel,
            AlertDelivery.recipient,
            AlertDelivery.round,
        ).where(
            AlertDelivery.workspace_id == workspace_id,
            AlertDelivery.alert_id.in_([a.id for a in alerts]),
        )
    )
    done: set[Told] = {(r.rule_id, r.alert_id, r.channel, r.recipient, r.round) for r in rows}
    count = 0
    for rule in rules:
        for alert in alerts:
            if alert.subject_id != rule.subject_id or alert.kind not in rule.conditions:
                continue
            # On stale data nobody is told: nothing says it is still so.
            if alert.certainty == "unverified":
                continue
            round_ = round_of(rule, alert, now)
            if round_ is None:
                continue
            count += len(await _send(session, rule, alert, round_=round_, now=now, done=done))
    await session.commit()
    return count
