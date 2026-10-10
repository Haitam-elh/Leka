"""Operations (LEKA-408): failure scenarios, end to end.

What these protect:
- A circuit breaker opens after repeated failures of a dependency, lets one
  try through once cooled down, closes when it answers, opens again at once
  when it does not — and never stands in the way when its own store (Redis)
  is down.
- A model provider failing for everyone is cut off: the gateway goes
  straight to the fallback — the degraded service — without asking it; a
  4xx the request caused does not count against the provider.
- The alert rules judge the snapshot — a broken check reads as firing,
  never as all clear; an alert is told when it starts, not again while it
  lasts (until reminded), and told when it resolves; one judgement at a time.
- The metrics answer only with the token, by route template, never an id;
  the health report says which component is down.
- A backup restores: dumped from one snapshot, restored aside, every table
  counted against its manifest — a changed count or a changed byte, refused.
"""

# ruff: noqa: F811 — the gateway's fixtures are imported to be requested by name.
from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from leka.api import ops as ops_api
from leka.capabilities.gateway import NoModelError
from leka.core import breaker
from leka.core.config import settings
from leka.db import session_factory, system_scope
from leka.ops import RULES, Rule, Snapshot, backup, forget, judge, take, watch
from leka.ops import alerts as alerts_module
from tests.test_model_gateway import (
    GOOGLE,
    MISTRAL,
    Script,
    _ask,
    _calls,
    ask,
    chat,
    gemini,
    workspace,  # noqa: F401 — a fixture
)

pytestmark = pytest.mark.integration

FAST = breaker.Policy(threshold=3, window_seconds=60, cooldown_seconds=1)


# ── circuit breakers ───────────────────────────────────────────────────────


async def test_a_breaker_opens_cools_tries_once_and_closes() -> None:
    name = f"test:{uuid.uuid4().hex[:6]}"
    assert await breaker.allow(name) and await breaker.state(name) == "closed"
    assert not await breaker.failure(name, FAST)
    assert not await breaker.failure(name, FAST)
    assert await breaker.failure(name, FAST)  # the third opens it
    assert not await breaker.allow(name) and await breaker.state(name) == "open"
    assert name in await breaker.known()

    await _cooled(name)
    # Half-open: ONE try goes through — the others wait for it.
    assert await breaker.state(name) == "half_open"
    assert await breaker.allow(name)
    assert not await breaker.allow(name)
    # It fails — open again, at once.
    assert await breaker.failure(name, FAST)
    assert not await breaker.allow(name)

    await _cooled(name)
    await breaker.success(name)
    assert await breaker.state(name) == "closed"
    # Closed again: failures count from nothing.
    assert not await breaker.failure(name, FAST)


async def _cooled(name: str) -> None:
    """The cooldown, over — without waiting for it."""
    import redis.asyncio as redis

    client = redis.from_url(str(settings.redis_url))
    try:
        await client.delete(f"{breaker.PREFIX}{name}:open")
    finally:
        await client.aclose()


async def test_a_breaker_whose_store_is_down_stands_in_no_one_s_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down() -> Any:
        raise ConnectionError("redis is down")

    monkeypatch.setattr(breaker, "_redis", down)
    assert await breaker.allow("anything")
    assert not await breaker.failure("anything")
    assert await breaker.state("anything") == "closed"


async def test_a_provider_failing_for_everyone_is_cut_off_and_the_fallback_answers(
    workspace: uuid.UUID,
) -> None:
    busy = httpx.Response(503, json={"error": {"message": "overloaded"}})
    # Google fails: once per request, its retries spent (two attempts each).
    # Five requests: the circuit opens.
    script = Script({GOOGLE: [busy] * 10, MISTRAL: [chat("From Mistral.")] * 5})
    for _ in range(5):
        done = await _ask(workspace, script, lambda g: g.complete(ask()))
        assert done.provider == "mistral"
    assert await breaker.state("model:google:leka") == "open"
    asked_google = sum(1 for r in script.asked if r.url.host == GOOGLE)

    # Open: Google is not asked at all — straight to the fallback.
    script.answers[MISTRAL].append(chat("Degraded, still answering."))
    done = await _ask(workspace, script, lambda g: g.complete(ask()))
    assert done.text == "Degraded, still answering."
    assert sum(1 for r in script.asked if r.url.host == GOOGLE) == asked_google
    calls = await _calls(workspace)
    assert calls[-1].provider == "mistral"


async def test_a_request_s_own_fault_does_not_count_against_the_provider(
    workspace: uuid.UUID,
) -> None:
    refused = httpx.Response(400, json={"error": {"message": "bad request"}})
    script = Script({GOOGLE: [refused] * 6, MISTRAL: [chat("ok")] * 6})
    for _ in range(6):
        await _ask(workspace, script, lambda g: g.complete(ask()))
    assert await breaker.state("model:google:leka") == "closed"


async def test_an_unusable_answer_is_the_request_s_problem_not_the_provider_s(
    workspace: uuid.UUID,
) -> None:
    # Answered — empty: retried, then the fallback; Google is up all along.
    script = Script({GOOGLE: [gemini("")] * 12, MISTRAL: [chat("ok")] * 6})
    for _ in range(6):
        await _ask(workspace, script, lambda g: g.complete(ask()))
    assert await breaker.state("model:google:leka") == "closed"


async def test_with_every_provider_cut_off_it_says_so(workspace: uuid.UUID) -> None:
    for _ in range(5):
        await breaker.failure("model:google:leka")
        await breaker.failure("model:mistral:leka")
    script = Script({GOOGLE: [gemini("never")], MISTRAL: [chat("never")]})
    with pytest.raises(NoModelError) as raised:
        await _ask(workspace, script, lambda g: g.complete(ask()))
    assert {a.error for a in raised.value.attempts} == {"circuit open"}
    assert script.asked == []


# ── alerts ─────────────────────────────────────────────────────────────────


def _healthy() -> Snapshot:
    return Snapshot(
        at=datetime.now(UTC),
        last_scheduled_seconds=30,
        last_job_finished_seconds=20,
        oldest_waiting_seconds=5,
        queue_depth={"leka:high": 0, "leka": 2, "leka:low": 10},
    )


def test_a_healthy_system_fires_nothing_and_each_failure_fires_its_rule() -> None:
    assert judge(_healthy()) == []
    cases: list[tuple[str, dict[str, Any]]] = [
        ("worker_stalled", {"oldest_waiting_seconds": 1200}),
        # Nothing finished for a while — and nothing scheduled either, since
        # the worker runs what schedules: the worker is told, not the
        # scheduler.
        ("worker_stalled", {"last_job_finished_seconds": 1200, "last_scheduled_seconds": 1200}),
        ("scheduler_stopped", {"last_scheduled_seconds": 3600}),
        ("queue_backlog", {"queue_depth": {"leka:low": 900}}),
        ("jobs_failing", {"jobs_failed_1h": 12}),
        ("models_failing", {"model_calls_1h": {("google", "ok"): 10, ("google", "failed"): 30}}),
        ("circuit_open", {"breakers": {"model:google:leka": "open"}}),
        ("connectors_failing", {"sync_runs_failed_1h": 7}),
        ("processing_failing", {"processing_runs_1h": 20, "processing_failed_1h": 9}),
        ("actions_failing", {"action_steps_1h": {"failed": 4, "succeeded": 1}}),
        ("system_unreadable", {"unreadable": ["ai"]}),
    ]
    for rule, change in cases:
        snap = _healthy()
        for field, value in change.items():
            setattr(snap, field, value)
        fired = judge(snap)
        assert [f.rule.name for f in fired] == [rule], (rule, fired)
        assert fired[0].why
    # Every rule has a runbook section; each name once.
    assert len({r.name for r in RULES}) == len(RULES)


def test_a_broken_check_reads_as_firing_never_as_all_clear() -> None:
    def broken(_: Snapshot) -> str | None:
        raise KeyError("oops")

    fired = judge(_healthy(), [Rule("broken", "critical", "Broken", "x", broken)])
    assert fired and "KeyError" in fired[0].why


def test_backups_expected_and_none_taken_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        alerts_module, "settings", settings.model_copy(update={"backup_expected": True})
    )
    snap = _healthy()
    assert [f.rule.name for f in judge(snap)] == ["backup_stale"]
    snap.last_backup_seconds = 3600
    assert judge(snap) == []
    snap.last_backup_seconds = 30 * 3600
    assert [f.rule.name for f in judge(snap)] == ["backup_stale"]


class Outbox:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, message: Any) -> None:
        self.sent.append(message)


async def _unlock() -> None:
    import redis.asyncio as redis

    client = redis.from_url(str(settings.redis_url))
    try:
        await client.delete(alerts_module.LOCK)
    finally:
        await client.aclose()


async def test_an_alert_is_told_when_it_starts_while_it_lasts_and_when_it_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox = Outbox()
    monkeypatch.setattr(alerts_module, "build_email_sender", lambda: outbox)
    monkeypatch.setattr(
        alerts_module,
        "settings",
        settings.model_copy(update={"ops_alert_emails": "ops@leka.example, cto@leka.example"}),
    )
    stalled = _healthy()
    stalled.oldest_waiting_seconds = 1500
    start = datetime.now(UTC)

    told = await watch(now=start, snap=stalled)
    assert told is not None and told.started == ("worker_stalled",)
    assert [m.to for m in outbox.sent] == ["ops@leka.example", "cto@leka.example"]
    assert (
        "critical" in outbox.sent[0].subject and "Jobs are not being run" in outbox.sent[0].subject
    )
    assert "docs/operations.md#worker-stalled" in outbox.sent[0].body
    # One judgement at a time: the next minute is locked.
    assert await watch(now=start, snap=stalled) is None

    await _unlock()
    told = await watch(now=start + timedelta(minutes=5), snap=stalled)
    assert told is not None and (told.started, told.reminded) == ((), ())
    assert len(outbox.sent) == 2  # not told again

    await _unlock()
    told = await watch(now=start + timedelta(hours=7), snap=stalled)
    assert told is not None and told.reminded == ("worker_stalled",)

    await _unlock()
    told = await watch(now=start + timedelta(hours=8), snap=_healthy())
    assert told is not None and told.resolved == ("worker_stalled",)
    assert "Resolved" in outbox.sent[-1].body and "resolved" in outbox.sent[-1].subject


async def test_with_redis_down_the_alerts_are_still_told(monkeypatch: pytest.MonkeyPatch) -> None:
    outbox = Outbox()
    monkeypatch.setattr(alerts_module, "build_email_sender", lambda: outbox)
    monkeypatch.setattr(
        alerts_module,
        "settings",
        settings.model_copy(update={"ops_alert_emails": "ops@leka.example"}),
    )

    class Down:
        async def set(self, *_: object, **__: object) -> None:
            raise ConnectionError("redis is down")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(alerts_module, "_client", lambda: Down())
    monkeypatch.setattr(alerts_module, "_memory", alerts_module._Memory())
    snap = _healthy()
    snap.unreadable = ["queues"]
    start = datetime.now(UTC)
    told = await watch(now=start, snap=snap)
    assert told is not None and told.started == ("system_unreadable",)
    assert len(outbox.sent) == 1
    # Kept in the process: not told again five minutes later.
    told = await watch(now=start + timedelta(minutes=5), snap=snap)
    assert told is not None and told.started == () and len(outbox.sent) == 1


async def test_the_snapshot_reads_the_system_and_the_scheduler_s_heartbeat() -> None:
    snap = await take()
    assert snap.unreadable == []
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO job_runs (job, queue, status, concurrency_key, attempts,"
                    " max_attempts, kwargs, args)"
                    " VALUES ('leka.ops.alerts.run_watch', 'leka:high', 'succeeded',"
                    " 'schedule:ops-watch', 1, 3, '{}', '[]')"
                )
            )
            await session.commit()
    try:
        snap = await take()
        assert snap.last_scheduled_seconds is not None and snap.last_scheduled_seconds < 60
        assert not any(f.rule.name == "scheduler_stopped" for f in judge(snap))
    finally:
        with system_scope():
            async with session_factory() as session:
                await session.execute(
                    text("DELETE FROM job_runs WHERE concurrency_key = 'schedule:ops-watch'")
                )
                await session.commit()


# ── metrics and health, over HTTP ──────────────────────────────────────────

TOKEN = "ops-test-token"


@pytest.fixture
def operator(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(
        ops_api, "settings", settings.model_copy(update={"metrics_token": SecretStr(TOKEN)})
    )
    return {"Authorization": f"Bearer {TOKEN}"}


async def test_the_metrics_are_for_whoever_holds_the_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No token configured: as if it did not exist.
    monkeypatch.setattr(ops_api, "settings", settings.model_copy(update={"metrics_token": None}))
    assert (await client.get("/api/v1/ops/metrics")).status_code == 404


async def test_the_metrics_say_the_system_by_route_never_an_id(
    client: AsyncClient, operator: dict[str, str]
) -> None:
    assert (await client.get("/api/v1/ops/metrics")).status_code == 401
    assert (
        await client.get("/api/v1/ops/metrics", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401
    some_id = uuid.uuid4()
    await client.get(f"/api/v1/agent-runs/{some_id}")
    await breaker.failure(f"action_endpoint:{some_id}", FAST)
    await breaker.failure(f"action_endpoint:{some_id}", FAST)
    await breaker.failure(f"action_endpoint:{some_id}", FAST)
    forget()
    answer = await client.get("/api/v1/ops/metrics", headers=operator)
    assert answer.status_code == 200 and answer.headers["content-type"].startswith("text/plain")
    said = answer.text
    for family in (
        "leka_up 1",
        "leka_http_requests_total",
        "leka_http_request_duration_seconds_bucket",
        "leka_jobs_failed_1h",
        "leka_queue_depth",
        "leka_model_calls_1h",
        "leka_runs_failed_1h",
        'leka_circuits_open{kind="action_endpoint"} 1',
    ):
        assert family in said, family
    assert 'route="/agent-runs/{run_id}"' in said
    assert str(some_id) not in said


async def test_the_health_report_says_which_component_is_down(
    client: AsyncClient, operator: dict[str, str]
) -> None:
    forget()
    answer = await client.get("/api/v1/ops/health", headers=operator)
    report = answer.json()
    found = {c["name"]: c for c in report["components"]}
    assert {"database", "redis", "object_store", "worker", "scheduler", "queues"} <= set(found)
    assert found["database"]["status"] == "ok" and found["redis"]["status"] == "ok"
    # No worker in the tests — nothing finished: down, said why, and LEKA down
    # with it. The scheduler is not blamed for what the worker does not run.
    assert found["worker"]["status"] == "down" and found["worker"]["detail"]
    assert found["scheduler"]["status"] == "ok"
    assert (report["status"], answer.status_code) == ("down", 503)


# ── backup and restore ─────────────────────────────────────────────────────

TOOLS = settings.pg_tools or shutil.which("pg_dump")


@pytest.mark.skipif(not TOOLS, reason="pg_dump and pg_restore: neither here nor LEKA_PG_TOOLS")
async def test_a_backup_restores_every_table_and_a_tampered_one_is_refused(
    tmp_path: Path,
) -> None:
    dumped = await backup.dump(tmp_path / "leka.dump")
    assert dumped.tables > 50 and dumped.manifest.exists()
    verified = await backup.verify(dumped.path)
    assert verified.ok and verified.tables == dumped.tables and verified.rows == dumped.rows

    # A count that does not match: refused, the table named.
    import json

    manifest = json.loads(dumped.manifest.read_text())
    manifest["tables"]["workspaces"] += 1
    dumped.manifest.write_text(json.dumps(manifest))
    refused = await backup.verify(dumped.path)
    assert not refused.ok and "workspaces" in refused.differences

    # A byte changed: refused before anything is restored.
    with dumped.path.open("ab") as tampered:
        tampered.write(b"\0")
    assert not (await backup.verify(dumped.path)).ok
