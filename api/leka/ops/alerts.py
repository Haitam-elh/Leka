"""Alerts (LEKA-408): the failure conditions an operator must hear about, judged
every few minutes on the snapshot — and said once, when they start, again if
they last, and when they end.

    RULES          what fires, how bad, what to do (its runbook section)
    judge()        the rules on a snapshot: which fire, said why — pure
    watch()        judged now, compared with what was already firing, told:
                   by email (LEKA_OPS_ALERT_EMAILS) and to Sentry

Run from two places, so that one going down cannot silence the alert about
it: the `ops-watch` job (the worker) and a loop in the API process (main.py).
A Redis lock keeps them from judging the same minute twice. When Redis and
the database are both gone, nothing in LEKA can tell — that is what the
external check on /api/v1/health is for (docs/operations.md).

What is firing lives in Redis (`leka:ops:alert:<rule>`): no migration, and a
Redis that forgets only means an alert still true is said again.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
import sentry_sdk
import structlog

from leka.core.config import settings
from leka.identity import EmailMessage, build_email_sender
from leka.ops.metrics import circuits
from leka.ops.snapshot import Snapshot, take

logger = structlog.get_logger(__name__)

STATE = "leka:ops:alert:"
LOCK = "leka:ops:watch:lock"
# Said again while it lasts, so it is not forgotten under other mail.
REMIND_EVERY = timedelta(hours=6)


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str  # critical: someone acts now · warning: today
    title: str
    runbook: str  # docs/operations.md#<this>
    fires: Callable[[Snapshot], str | None]  # why, or None


def worker_stalled(s: Snapshot) -> str | None:
    if s.oldest_waiting_seconds is not None and s.oldest_waiting_seconds > 600:
        return f"a job has waited {int(s.oldest_waiting_seconds // 60)} min for a worker"
    return None


def scheduler_stopped(s: Snapshot) -> str | None:
    if s.last_scheduled_seconds is None:
        return "no sweep was ever scheduled in the last 7 days"
    if s.last_scheduled_seconds > 900:
        return f"nothing scheduled for {int(s.last_scheduled_seconds // 60)} min"
    return None


def queue_backlog(s: Snapshot) -> str | None:
    waiting = sum(s.queue_depth.values())
    return f"{waiting} jobs waiting in the queues" if waiting > 500 else None


def _jobs(s: Snapshot) -> str | None:
    return f"{s.jobs_failed_1h} jobs failed in the last hour" if s.jobs_failed_1h >= 10 else None


def _models(s: Snapshot) -> str | None:
    rate = s.model_error_rate_1h
    calls = sum(s.model_calls_1h.values())
    if rate is not None and calls >= 20 and rate > 0.25:
        return f"{rate:.0%} of {calls} model calls failed in the last hour"
    return None


def _circuits(s: Snapshot) -> str | None:
    opened = {k: n for k, n in circuits(s).items() if n}
    if not opened:
        return None
    return "open: " + ", ".join(f"{k} ({n})" if n > 1 else k for k, n in sorted(opened.items()))


def _connectors(s: Snapshot) -> str | None:
    if s.sync_runs_failed_1h >= 5:
        return f"{s.sync_runs_failed_1h} sync passes failed in the last hour"
    return None


def _processing(s: Snapshot) -> str | None:
    if s.processing_runs_1h >= 10 and s.processing_failed_1h / s.processing_runs_1h > 0.2:
        return f"{s.processing_failed_1h} of {s.processing_runs_1h} processing runs failed"
    return None


def _actions(s: Snapshot) -> str | None:
    failed = s.action_steps_1h.get("failed", 0)
    return (
        f"{failed} actions on customers' systems failed in the last hour" if failed >= 3 else None
    )


def backup_stale(s: Snapshot) -> str | None:
    if not settings.backup_expected:
        return None
    if s.last_backup_seconds is None:
        return "no backup was ever uploaded"
    if s.last_backup_seconds > 26 * 3600:
        return f"the last good backup is {s.last_backup_seconds / 3600:.0f} h old"
    return None


def _unreadable(s: Snapshot) -> str | None:
    return f"could not read: {', '.join(s.unreadable)}" if s.unreadable else None


RULES: Sequence[Rule] = (
    Rule("worker_stalled", "critical", "Jobs are not being run", "worker-stalled", worker_stalled),
    Rule(
        "scheduler_stopped",
        "critical",
        "The scheduler is not scheduling",
        "scheduler-stopped",
        scheduler_stopped,
    ),
    Rule(
        "system_unreadable",
        "critical",
        "LEKA cannot read its own state",
        "system-unreadable",
        _unreadable,
    ),
    Rule(
        "queue_backlog", "warning", "The job queues are backing up", "queue-backlog", queue_backlog
    ),
    Rule("jobs_failing", "warning", "Background jobs are failing", "jobs-failing", _jobs),
    Rule("models_failing", "critical", "Model calls are failing", "models-failing", _models),
    Rule(
        "circuit_open",
        "warning",
        "A dependency is cut off by its circuit breaker",
        "circuit-open",
        _circuits,
    ),
    Rule(
        "connectors_failing",
        "warning",
        "Sources are failing to sync",
        "connectors-failing",
        _connectors,
    ),
    Rule(
        "processing_failing", "warning", "Processing is failing", "processing-failing", _processing
    ),
    Rule(
        "actions_failing",
        "critical",
        "Actions on customers' systems are failing",
        "actions-failing",
        _actions,
    ),
    Rule("backup_stale", "critical", "Backups are not being taken", "backup-stale", backup_stale),
)


@dataclass(frozen=True)
class Firing:
    rule: Rule
    why: str


def judge(snap: Snapshot, rules: Sequence[Rule] = RULES) -> list[Firing]:
    """What fires on this snapshot, and why. Pure: a rule that crashes is
    said as firing — a broken check must not read as all clear."""
    firing: list[Firing] = []
    for rule in rules:
        try:
            why = rule.fires(snap)
        except Exception as error:
            why = f"the check itself failed: {type(error).__name__}"
        if why:
            firing.append(Firing(rule, why))
    return firing


@dataclass(frozen=True)
class Told:
    """What one watch said: started, still firing (reminded), resolved."""

    started: tuple[str, ...] = ()
    reminded: tuple[str, ...] = ()
    resolved: tuple[str, ...] = ()


def _client() -> redis.Redis:
    return redis.from_url(str(settings.redis_url), socket_connect_timeout=2, socket_timeout=2)


async def watch(*, now: datetime | None = None, snap: Snapshot | None = None) -> Told | None:
    """Judged now and told. None: another process is judging this minute."""
    moment = now or datetime.now(UTC)
    client = _client()
    try:
        if not await client.set(LOCK, moment.isoformat(), nx=True, ex=240):
            return None
        snapshot = snap or await take(moment)
        firing = {f.rule.name: f for f in judge(snapshot)}
        started: list[Firing] = []
        reminded: list[Firing] = []
        resolved: list[tuple[Rule, dict[str, str]]] = []
        for rule in RULES:
            key = f"{STATE}{rule.name}"
            raw = await client.get(key)
            known = json.loads(raw) if raw else None
            now_firing = firing.get(rule.name)
            if now_firing is not None and known is None:
                started.append(now_firing)
                await client.set(
                    key, json.dumps({"since": moment.isoformat(), "told": moment.isoformat()})
                )
            elif now_firing is not None and known is not None:
                if moment - datetime.fromisoformat(known["told"]) >= REMIND_EVERY:
                    reminded.append(now_firing)
                    await client.set(key, json.dumps({**known, "told": moment.isoformat()}))
            elif known is not None:
                resolved.append((rule, known))
                await client.delete(key)
    finally:
        await client.aclose()
    if started or reminded or resolved:
        await _tell(started, reminded, resolved, moment)
    return Told(
        tuple(f.rule.name for f in started),
        tuple(f.rule.name for f in reminded),
        tuple(r.name for r, _ in resolved),
    )


def _message(
    started: Sequence[Firing],
    reminded: Sequence[Firing],
    resolved: Sequence[tuple[Rule, dict[str, str]]],
    moment: datetime,
) -> tuple[str, str]:
    worst = (
        "critical"
        if any(f.rule.severity == "critical" for f in (*started, *reminded))
        else ("warning" if started or reminded else "resolved")
    )
    names = [f.rule.title for f in (*started, *reminded)] or [r.title for r, _ in resolved]
    subject = f"[LEKA {settings.environment} · {worst}] {names[0]}" + (
        f" (+{len(names) - 1})" if len(names) > 1 else ""
    )
    lines = [f"LEKA, {settings.environment} — {moment.strftime('%Y-%m-%d %H:%M UTC')}", ""]
    for heading, items in (("Started", started), ("Still firing", reminded)):
        if items:
            lines.append(f"{heading}:")
            lines += [
                f"  · [{f.rule.severity}] {f.rule.title} — {f.why}\n"
                f"    What to do: docs/operations.md#{f.rule.runbook}"
                for f in items
            ]
            lines.append("")
    if resolved:
        lines.append("Resolved:")
        lines += [f"  · {r.title} (since {known.get('since', '?')})" for r, known in resolved]
    return subject, "\n".join(lines).rstrip() + "\n"


async def _tell(
    started: Sequence[Firing],
    reminded: Sequence[Firing],
    resolved: Sequence[tuple[Rule, dict[str, str]]],
    moment: datetime,
) -> None:
    subject, body = _message(started, reminded, resolved, moment)
    logger.warning(
        "ops_alert",
        started=[f.rule.name for f in started],
        reminded=[f.rule.name for f in reminded],
        resolved=[r.name for r, _ in resolved],
    )
    if started or reminded:
        sentry_sdk.capture_message(subject, level="error")
    recipients = [a.strip() for a in (settings.ops_alert_emails or "").split(",") if a.strip()]
    if not recipients:
        return
    sender = build_email_sender()
    for to in recipients:
        try:
            await sender.send(EmailMessage(to=to, subject=subject, body=body))
        except Exception:
            # Sentry and the log still have it: one channel down is not none.
            logger.exception("ops_alert_unsent", to_domain=to.rsplit("@", 1)[-1])


def run_watch() -> dict[str, list[str]]:
    """Entry point for the schedule."""
    import asyncio

    told = asyncio.run(watch())
    if told is None:
        return {"skipped": ["locked"]}
    return {
        "started": list(told.started),
        "reminded": list(told.reminded),
        "resolved": list(told.resolved),
    }
