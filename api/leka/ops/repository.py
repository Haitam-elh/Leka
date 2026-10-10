"""How LEKA is doing, read once (LEKA-408): what the metrics expose, what the
health report says, what the alert rules judge — the same numbers for all
three, so a dashboard and an alert never disagree.

Read across every workspace (system scope): this is operating data — counts,
ages, rates — never a customer's. No name, no text, no id of anything a
customer owns leaves here.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core import breaker
from leka.core.config import settings
from leka.db import session_factory, system_scope

QUEUES = ("leka:high", "leka", "leka:low")


@dataclass
class Snapshot:
    at: datetime
    # Background jobs: how many in each live state; failed in the last hour;
    # the oldest still waiting; when a worker last finished one; when the
    # scheduler last put a sweep on the queue.
    jobs: dict[str, int] = field(default_factory=dict)
    jobs_failed_1h: int = 0
    oldest_waiting_seconds: float | None = None
    last_job_finished_seconds: float | None = None
    last_scheduled_seconds: float | None = None
    queue_depth: dict[str, int] = field(default_factory=dict)
    # Connectors: sources by status and health; capabilities failing to sync;
    # passes and processing stages failed in the last hour.
    sources: dict[tuple[str, str], int] = field(default_factory=dict)
    syncs_failing: int = 0
    sync_runs_failed_1h: int = 0
    processing_failed_1h: int = 0
    processing_runs_1h: int = 0
    # AI: model calls in the last hour by provider and outcome, their mean
    # latency; what they cost in the last day; agents and workflows.
    model_calls_1h: dict[tuple[str, str], int] = field(default_factory=dict)
    model_latency_ms_1h: dict[str, float] = field(default_factory=dict)
    model_cost_usd_24h: float = 0.0
    agent_runs: dict[str, int] = field(default_factory=dict)
    agent_runs_failed_1h: int = 0
    workflow_runs: dict[str, int] = field(default_factory=dict)
    workflow_runs_failed_1h: int = 0
    # Actions LEKA ran on customers' systems: done and failed, last hour.
    action_steps_1h: dict[str, int] = field(default_factory=dict)
    # Circuit breakers: every one that has opened, and its state now.
    breakers: dict[str, str] = field(default_factory=dict)
    # Since the last good backup was uploaded (leka.ops.backup); None: never.
    last_backup_seconds: float | None = None
    # What could not be read: a broken probe is said, never a crash.
    unreadable: list[str] = field(default_factory=list)

    @property
    def model_error_rate_1h(self) -> float | None:
        total = sum(self.model_calls_1h.values())
        if total == 0:
            return None
        failed = sum(n for (_, outcome), n in self.model_calls_1h.items() if outcome == "failed")
        return failed / total


async def _rows(session: AsyncSession, sql: str) -> list[tuple[object, ...]]:
    return [tuple(r) for r in (await session.execute(text(sql))).all()]


async def _scalar(session: AsyncSession, sql: str) -> object:
    return (await session.execute(text(sql))).scalar()


def _seconds(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


# What a scrape, a health check and the alerts read within this many seconds
# of each other is read once: a Prometheus scraping every 15 seconds must not
# keep the database busy counting.
CACHE_SECONDS = 15.0
_cache: list[tuple[float, Snapshot]] = []


async def cached() -> Snapshot:
    """The last snapshot if it is fresh enough, a new one otherwise."""
    if _cache and time.monotonic() - _cache[0][0] < CACHE_SECONDS:
        return _cache[0][1]
    snap = await take()
    _cache[:] = [(time.monotonic(), snap)]
    return snap


def forget() -> None:
    """For the tests: the next `cached()` reads again."""
    _cache.clear()


async def take(now: datetime | None = None) -> Snapshot:
    """Everything, read now. Each part is read on its own: one that fails is
    named in `unreadable`, and the rest still answers."""
    snap = Snapshot(at=now or datetime.now(UTC))
    with system_scope():
        async with session_factory() as session:
            for name, read in (
                ("jobs", _jobs),
                ("connectors", _connectors),
                ("ai", _ai),
                ("actions", _actions),
            ):
                try:
                    await read(session, snap)
                except Exception:
                    await session.rollback()
                    snap.unreadable.append(name)
    try:
        await _queues(snap)
    except Exception:
        snap.unreadable.append("queues")
    snap.breakers = dict(await breaker.states())
    return snap


async def _jobs(session: AsyncSession, snap: Snapshot) -> None:
    for status, count in await _rows(
        session,
        "SELECT status, count(*) FROM job_runs"
        " WHERE status IN ('queued', 'running', 'retrying') GROUP BY status",
    ):
        snap.jobs[str(status)] = int(str(count))
    snap.jobs_failed_1h = int(
        str(
            await _scalar(
                session,
                "SELECT count(*) FROM job_runs"
                " WHERE status = 'failed' AND finished_at > now() - interval '1 hour'",
            )
        )
    )
    snap.oldest_waiting_seconds = _seconds(
        await _scalar(
            session,
            "SELECT extract(epoch FROM now() - min(created_at))::float FROM job_runs"
            " WHERE status = 'queued'",
        )
    )
    snap.last_job_finished_seconds = _seconds(
        await _scalar(
            session,
            "SELECT extract(epoch FROM now() - max(finished_at))::float FROM job_runs"
            " WHERE finished_at > now() - interval '7 days'",
        )
    )
    snap.last_scheduled_seconds = _seconds(
        await _scalar(
            session,
            "SELECT extract(epoch FROM now() - max(created_at))::float FROM job_runs"
            " WHERE for_workspace_id IS NULL AND concurrency_key LIKE 'schedule:%'"
            " AND created_at > now() - interval '7 days'",
        )
    )


async def _connectors(session: AsyncSession, snap: Snapshot) -> None:
    for status, health, count in await _rows(
        session, "SELECT status, health_status, count(*) FROM sources GROUP BY 1, 2"
    ):
        snap.sources[(str(status), str(health))] = int(str(count))
    snap.syncs_failing = int(
        str(await _scalar(session, "SELECT count(*) FROM source_syncs WHERE status = 'failed'"))
    )
    snap.sync_runs_failed_1h = int(
        str(
            await _scalar(
                session,
                "SELECT count(*) FROM sync_runs WHERE status IN ('failed', 'abandoned')"
                " AND started_at > now() - interval '1 hour'",
            )
        )
    )
    total, failed = (
        await session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE status IN ('failed', 'abandoned'))"
                " FROM processing_runs WHERE started_at > now() - interval '1 hour'"
            )
        )
    ).one()
    snap.processing_runs_1h, snap.processing_failed_1h = int(total), int(failed)


async def _ai(session: AsyncSession, snap: Snapshot) -> None:
    latency: dict[str, list[float]] = defaultdict(list)
    for provider, status, count, mean in await _rows(
        session,
        "SELECT provider, status, count(*), avg(latency_ms)::float FROM model_calls"
        " WHERE at > now() - interval '1 hour' GROUP BY 1, 2",
    ):
        snap.model_calls_1h[(str(provider), str(status))] = int(str(count))
        if status == "ok" and isinstance(mean, int | float):
            latency[str(provider)].append(float(mean))
    snap.model_latency_ms_1h = {p: sum(v) / len(v) for p, v in latency.items()}
    cost = await _scalar(
        session,
        "SELECT coalesce(sum(cost_usd), 0)::float FROM model_calls"
        " WHERE at > now() - interval '1 day'",
    )
    snap.model_cost_usd_24h = float(cost) if isinstance(cost, int | float) else 0.0
    for table, live, failed_attr in (
        ("agent_runs", snap.agent_runs, "agent_runs_failed_1h"),
        ("workflow_runs", snap.workflow_runs, "workflow_runs_failed_1h"),
    ):
        for status, count in await _rows(
            session,
            f"SELECT status, count(*) FROM {table}"  # noqa: S608 — a table name of ours
            " WHERE status IN ('awaiting_approval', 'queued', 'running') GROUP BY status",
        ):
            live[str(status)] = int(str(count))
        failed = await _scalar(
            session,
            f"SELECT count(*) FROM {table}"  # noqa: S608 — a table name of ours
            " WHERE status = 'failed' AND finished_at > now() - interval '1 hour'",
        )
        setattr(snap, failed_attr, int(str(failed)))


async def _actions(session: AsyncSession, snap: Snapshot) -> None:
    for status, count in await _rows(
        session,
        "SELECT status, count(*) FROM intention_plan_steps"
        " WHERE status IN ('succeeded', 'failed') AND finished_at > now() - interval '1 hour'"
        " GROUP BY status",
    ):
        snap.action_steps_1h[str(status)] = int(str(count))


async def _queues(snap: Snapshot) -> None:
    # Here, not at the top: `python -m leka.ops.backup` must be the first to
    # import its module.
    from leka.ops.backup import LAST_BACKUP, last_uploaded

    client = redis.from_url(str(settings.redis_url), socket_connect_timeout=1, socket_timeout=1)
    try:
        for queue in QUEUES:
            snap.queue_depth[queue] = int(await client.llen(f"rq:queue:{queue}"))
        last = await client.get(LAST_BACKUP)
        if last:
            at: datetime | None = datetime.fromisoformat(json.loads(last)["at"])
        elif settings.backup_expected:
            # Redis forgot it: the bucket says it — and Redis is told again.
            at = await asyncio.to_thread(last_uploaded)
            if at is not None:
                await client.set(LAST_BACKUP, json.dumps({"at": at.isoformat(), "from": "bucket"}))
        else:
            at = None
        if at is not None:
            snap.last_backup_seconds = (snap.at - at).total_seconds()
    finally:
        await client.aclose()
