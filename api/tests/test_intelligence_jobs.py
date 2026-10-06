"""When LEKA analyses (LEKA-377): asked, told by the model, swept.

What these protect: anyone who may ask LEKA something may ask for a run —
every analysis or those named, an unknown name refused before anything is
queued; the catalogue says what each analysis reads and whether it can run;
a build of the model queues a run, beside the contexts' pass; the hourly
sweep queues the workspaces whose analysis is behind — never analysed, a
newer build, a new catalogue, a day old — and not the others; it closes
the runs a dead worker left, forgets old runs but never a workspace's
latest, and findings resolved a year ago.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.background.routes import ROUTES
from leka.db import session_factory, system_scope, workspace_scope
from leka.intelligence import ANALYZERS, Finding, IntelligenceRun, catalogue_hash
from leka.intelligence import job as intelligence_job
from leka.knowledge import ModelRun
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/intelligence"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class Queued:
    """What would have been queued, and whether a run was already on its way."""

    def __init__(self, *, busy: bool = False) -> None:
        self.busy = busy
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, workspace_id: uuid.UUID, **kwargs: Any) -> bool:
        self.calls.append({"workspace": workspace_id, **kwargs})
        return not self.busy


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> Queued:
    fake = Queued()
    monkeypatch.setattr(intelligence_job, "queue_run", fake)
    monkeypatch.setattr("leka.api.intelligence.queue_run", fake)
    return fake


# ── asked ──────────────────────────────────────────────────────────────


async def test_a_member_asks_for_a_run_of_every_analysis_or_those_named(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], queued: Queued
) -> None:
    _as(identity, acme, "member")

    every = await client.post(f"{API}/runs", json={})
    named = await client.post(f"{API}/runs", json={"analyzers": ["ownership"]})

    assert (every.status_code, every.json()) == (202, {"queued": True})
    assert named.status_code == 202
    assert queued.calls == [
        {"workspace": acme["acme"], "trigger": "request", "by": acme["member"], "analyzers": ()},
        {
            "workspace": acme["acme"],
            "trigger": "request",
            "by": acme["member"],
            "analyzers": ["ownership"],
        },
    ]


async def test_an_unknown_analysis_is_refused_before_anything_is_queued(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], queued: Queued
) -> None:
    _as(identity, acme, "member")

    refused = await client.post(f"{API}/runs", json={"analyzers": ["ownership", "astrology"]})

    assert refused.status_code == 422
    assert "astrology" in refused.text
    assert queued.calls == []


async def test_a_run_already_on_its_way_answers_instead(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], queued: Queued
) -> None:
    _as(identity, acme, "admin")
    queued.busy = True

    response = await client.post(f"{API}/runs", json={})

    assert (response.status_code, response.json()) == (202, {"queued": False})


async def test_the_catalogue_says_what_each_analysis_reads(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "member")

    found = (await client.get(f"{API}/analyzers")).json()

    assert [a["name"] for a in found] == [a.name for a in ANALYZERS]
    context = next(a for a in found if a["name"] == "context_health")
    assert (context["reads"], context["method"], context["available"]) == (
        ["context"],
        "rules",
        True,
    )


# ── told by the model ──────────────────────────────────────────────────


def test_a_build_of_the_model_is_analysed_beside_the_contexts_pass() -> None:
    jobs = [route.job for route in ROUTES["knowledge.model_built"]]

    assert jobs == [
        "leka.context.job.run_follow_for_event",
        "leka.intelligence.job.run_intelligence_for_event",
    ]


# ── swept ──────────────────────────────────────────────────────────────


async def _built(workspace: uuid.UUID, at: datetime) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            session.add(
                ModelRun(
                    workspace_id=workspace,
                    status="succeeded",
                    started_at=at - timedelta(minutes=1),
                    finished_at=at,
                    model_version=1,
                )
            )
            await session.commit()


async def _ran(
    workspace: uuid.UUID,
    at: datetime,
    *,
    built: datetime | None,
    status: str = "succeeded",
    catalogue: str | None = None,
) -> uuid.UUID:
    with workspace_scope(workspace):
        async with session_factory() as session:
            run = IntelligenceRun(
                workspace_id=workspace,
                status=status,
                trigger="model",
                requested=[],
                started_at=at,
                finished_at=None if status == "running" else at,
                model_built_at=built,
                catalogue=catalogue or catalogue_hash(ANALYZERS),
                counts={},
            )
            session.add(run)
            await session.commit()
            return run.id


async def test_the_sweep_queues_only_the_workspaces_behind(
    acme: dict[str, uuid.UUID], queued: Queued
) -> None:
    built = NOW - timedelta(hours=2)
    # Acme: built, analysed from that build an hour ago — up to date.
    await _built(acme["acme"], built)
    await _ran(acme["acme"], NOW - timedelta(hours=1), built=built)
    # Globex: built, never analysed.
    await _built(acme["globex"], built)

    await intelligence_job.sweep_intelligence(now=NOW)
    assert [call["workspace"] for call in queued.calls if call["workspace"] in acme.values()] == [
        acme["globex"]
    ]

    queued.calls.clear()
    # Acme's model built again since: behind.
    await _built(acme["acme"], NOW - timedelta(minutes=10))
    await intelligence_job.sweep_intelligence(now=NOW)
    assert acme["acme"] in [call["workspace"] for call in queued.calls]
    assert all(call["trigger"] == "schedule" for call in queued.calls)


async def test_a_new_catalogue_or_a_day_without_a_run_is_behind_too(
    acme: dict[str, uuid.UUID], queued: Queued
) -> None:
    built = NOW - timedelta(days=3)
    await _built(acme["acme"], built)
    await _ran(acme["acme"], NOW - timedelta(hours=1), built=built, catalogue="an older one")
    await _built(acme["globex"], built)
    await _ran(acme["globex"], NOW - timedelta(hours=25), built=built)

    await intelligence_job.sweep_intelligence(now=NOW)

    behind = {call["workspace"] for call in queued.calls}
    assert {acme["acme"], acme["globex"]} <= behind


async def test_the_sweep_closes_dead_runs_and_forgets_old_ones_but_the_latest(
    acme: dict[str, uuid.UUID], queued: Queued
) -> None:
    dead = await _ran(acme["acme"], NOW - timedelta(days=1), built=None, status="running")
    old = await _ran(acme["acme"], NOW - timedelta(days=120), built=None)
    lone = await _ran(acme["globex"], NOW - timedelta(days=200), built=None)
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            for resolved_at, key in ((NOW - timedelta(days=400), "long ago"), (NOW, "today")):
                session.add(
                    Finding(
                        workspace_id=acme["acme"],
                        analyzer="ownership",
                        analyzer_version=1,
                        key=key,
                        category="organisation",
                        code="ownership.no_owner",
                        params={},
                        statement=key,
                        severity="low",
                        rank=100,
                        confidence=0.9,
                        subject_type="entity",
                        subject_name=key,
                        status="resolved",
                        first_seen_at=resolved_at - timedelta(days=1),
                        last_seen_at=resolved_at - timedelta(days=1),
                        resolved_at=resolved_at,
                        first_run_id=old,
                        last_run_id=old,
                        resolved_run_id=old,
                    )
                )
            await session.commit()

    result = await intelligence_job.sweep_intelligence(now=NOW)

    assert result["abandoned"] >= 1
    with system_scope():
        async with session_factory() as session:
            runs = {
                run.id: run
                for run in (
                    await session.execute(
                        select(IntelligenceRun).where(IntelligenceRun.id.in_([dead, old, lone]))
                    )
                ).scalars()
            }
            keys = set(
                (
                    await session.execute(
                        select(Finding.key).where(Finding.workspace_id == acme["acme"])
                    )
                ).scalars()
            )
    assert (runs[dead].status, runs[dead].error) == ("abandoned", "WorkerLost")
    assert old not in runs
    # Globex's only run, however old: its latest.
    assert lone in runs
    assert keys == {"today"}
