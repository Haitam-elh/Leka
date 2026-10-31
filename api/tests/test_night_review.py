"""The night review (2026-10-29): what LEKA went through overnight, and what
it found to look at — on Acme's company model (test_context_engine).

What these protect: none before the first; a review asked now, kept, what
it read counted — the things of the model, the sources, the alerts — and
its points the most serious first, each with where it is seen and whether
LEKA can be asked about it: an alert open, a source in error, a pull
request of LEKA's in red; every workspace reviewed by the night's job, one
failing never stopping the others; another workspace's never read.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.capabilities import AgentRun, CodeChange
from leka.connectors import Source, SourceStatus, SyncStatus
from leka.db import session_factory, system_scope, workspace_scope
from leka.intelligence import Finding
from leka.monitoring import MonitoringAlert, NightReview
from leka.monitoring.night import review_every_workspace, still
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_analysis_api import queued  # noqa: F401 — a fixture
from tests.test_sources_api import _as, _create, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/monitoring/night-review"
ASKED = "Qui est responsable de Billing API ?"


async def _troubles(workspace_id: uuid.UUID, source_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            session.add(
                MonitoringAlert(
                    workspace_id=workspace_id,
                    id=uuid.uuid4(),
                    subject_type="entity",
                    subject_id=uuid.uuid4(),
                    subject_name="payment-api",
                    family="health",
                    kind="unavailable",
                    severity="high",
                    certainty="confirmed",
                    status="open",
                    opened_at=now,
                    last_seen_at=now,
                )
            )
            source = await session.get(Source, source_id)
            assert source is not None
            source.status = SourceStatus.ERROR
            await session.commit()


async def test_a_review_says_what_it_read_and_what_to_look_at_most_serious_first(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    assert (await client.get(API)).json() is None
    created: dict[str, Any] = await _create(client)
    await _troubles(acme["acme"], uuid.UUID(created["id"]))

    asked = await client.post(API)
    assert asked.status_code == 200, asked.text
    said = asked.json()
    assert said["trigger"] == "asked"
    assert said["checked"]["things"] > 0 and said["checked"]["sources"] >= 1
    assert said["checked"]["alerts"] == 1
    kinds = [(p["kind"], p["severity"]) for p in said["points"]]
    assert ("alert", "high") in kinds and ("source", "high") in kinds
    severities = [p["severity"] for p in said["points"]]
    assert severities == sorted(severities, key=["high", "medium", "low"].index)
    [alert] = [p for p in said["points"] if p["kind"] == "alert"]
    assert alert["name"] == "payment-api" and alert["ask"] is True
    assert alert["params"]["trouble"] == "unavailable"
    [source] = [p for p in said["points"] if p["kind"] == "source"]
    assert source["href"] == f"/sources/{created['id']}" and source["params"]["why"] == "error"
    # Read back: the last one.
    assert (await client.get(API)).json()["id"] == said["id"]

    # Another workspace's is never read.
    _as(identity, acme, "other_admin")
    assert (await client.get(API)).json() is None


async def test_the_night_reviews_every_workspace(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    created: dict[str, Any] = await _create(client)
    # A pull request of LEKA's, in red.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            session.add(
                CodeChange(
                    workspace_id=acme["acme"],
                    id=uuid.uuid4(),
                    source_id=uuid.UUID(created["id"]),
                    repository="acme/payments",
                    base_branch="main",
                    title="Déduire les paiements en attente",
                    status="applied",
                    pull_request_number=7,
                    follow={"stage": "checks_failed"},
                )
            )
            await session.commit()
    done = await review_every_workspace()
    assert done["reviewed"] >= 2 and done["failed"] == 0
    with system_scope():
        async with session_factory() as session:
            rows = (
                await session.scalars(
                    select(NightReview).where(NightReview.workspace_id == acme["acme"])
                )
            ).all()
    [row] = rows
    assert row.trigger == "night" and int(str(row.checked["things"])) > 0
    [change] = [p for p in row.points if p["kind"] == "change"]
    assert (change["severity"], change["name"]) == ("high", "Déduire les paiements en attente")
    assert change["params"] == {"number": 7}


async def test_what_leka_works_on_now_each_with_its_step_and_where(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    assert (await client.get("/api/v1/monitoring/now")).json() == []
    asked = await client.post("/api/v1/intentions", json={"text": ASKED})
    assert asked.status_code == 201, asked.text
    intention = asked.json()["intention"]["id"]
    created: dict[str, Any] = await _create(client)
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            source = await session.get(Source, uuid.UUID(created["id"]))
            assert source is not None
            source.sync_status = SyncStatus.RUNNING
            session.add(
                CodeChange(
                    workspace_id=acme["acme"],
                    id=uuid.uuid4(),
                    source_id=source.id,
                    repository="acme/payments",
                    base_branch="main",
                    title="Déduire les paiements en attente",
                    status="applied",
                    pull_request_number=7,
                    repairs=[{"state": "running", "asked_at": datetime.now(UTC).isoformat()}],
                )
            )
            await session.commit()
    now = (await client.get("/api/v1/monitoring/now")).json()
    by = {item["kind"]: item for item in now}
    assert (by["intention"]["step"], by["intention"]["href"]) == (
        "analysing",
        f"/intentions/{intention}",
    )
    assert by["source"]["step"] == "reading" and by["source"]["href"] == f"/sources/{created['id']}"
    assert (by["repair"]["step"], by["repair"]["title"]) == (
        "repairing",
        "Déduire les paiements en attente",
    )
    _as(identity, acme, "other_admin")
    assert (await client.get("/api/v1/monitoring/now")).json() == []


async def _red_change(workspace: uuid.UUID, source: uuid.UUID, intention: uuid.UUID | None) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            session.add(
                CodeChange(
                    workspace_id=workspace,
                    id=uuid.uuid4(),
                    source_id=source,
                    intention_id=intention,
                    repository="acme/payments",
                    base_branch="main",
                    title="Implémente le design de l'accueil",
                    status="applied",
                    pull_request_number=450,
                    follow={"stage": "checks_failed"},
                )
            )
            await session.commit()


async def test_a_point_settled_since_is_gone_at_once_never_a_deleted_intention_s(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[uuid.UUID],
) -> None:
    # 2026-10-31: the pull request #450's intention deleted, the review still
    # said it, its « Voir » leading nowhere.
    _as(identity, acme, "admin")
    asked = await client.post("/api/v1/intentions", json={"text": ASKED})
    intention = asked.json()["intention"]["id"]
    created: dict[str, Any] = await _create(client)
    await _red_change(acme["acme"], uuid.UUID(created["id"]), uuid.UUID(intention))
    said = (await client.post(API)).json()
    [change] = [p for p in said["points"] if p["kind"] == "change"]
    assert change["href"] == f"/intentions/{intention}/deliverable"
    assert said["settled"] == 0

    assert (await client.delete(f"/api/v1/intentions/{intention}")).status_code == 200
    now = (await client.get(API)).json()
    assert [p for p in now["points"] if p["kind"] == "change"] == []
    assert now["settled"] == 1 and now["id"] == said["id"]
    # And the next review never says it again.
    again = (await client.post(API)).json()
    assert [p for p in again["points"] if p["kind"] == "change"] == []


async def test_each_finding_and_each_failing_agent_is_a_point_seen_where_it_is(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    now = datetime.now(UTC)
    entity = uuid.uuid4()
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            session.add(
                Finding(
                    workspace_id=acme["acme"],
                    analyzer="health",
                    analyzer_version=1,
                    key=f"entity:{entity}",
                    category="health",
                    code="health.unavailable",
                    params={},
                    statement="Redis is down.",
                    severity="high",
                    rank=10,
                    confidence=0.9,
                    subject_type="entity",
                    subject_id=entity,
                    subject_name="Redis",
                    subject_kind="database",
                    status="open",
                    first_seen_at=now,
                    last_seen_at=now,
                    first_run_id=uuid.uuid4(),
                    last_run_id=uuid.uuid4(),
                    occurrences=1,
                    reopened=0,
                )
            )
            for _ in range(2):
                session.add(
                    AgentRun(
                        workspace_id=acme["acme"],
                        key="documentation-assistant",
                        version="1.0.0",
                        status="failed",
                        inputs={},
                        requested_by=acme["admin"],
                        format="markdown",
                        detail={},
                        queued_at=now,
                        finished_at=now,
                    )
                )
            await session.commit()
    said = (await client.post(API)).json()
    [finding] = [p for p in said["points"] if p["kind"] == "finding"]
    assert (finding["name"], finding["ask"]) == ("Redis", True)
    assert finding["params"]["subject_id"] == str(entity)
    assert finding["params"]["subject_kind"] == "database"
    [run] = [p for p in said["points"] if p["kind"] == "run"]
    assert (run["name"], run["count"], run["href"]) == (
        "Assistant de documentation",
        2,
        "/capabilities/documentation-assistant",
    )
    alerts = [p for p in said["points"] if p["kind"] == "alert"]
    assert all(p["href"] == "/environment#alerts" for p in alerts)


def test_what_still_stands_is_said_as_it_is_now_and_what_was_settled_counted() -> None:
    point = {"kind": "decisions", "severity": "medium", "count": 2, "params": {}}
    alert = {"kind": "alert", "severity": "high", "name": "api", "params": {"trouble": "degraded"}}
    # Fewer decisions now: as they are now; the alert gone: settled.
    now = [{**point, "count": 1}]
    shown, settled = still([alert, point], now)
    assert shown == now and settled == 1
    # Kept counted before 2026-10-31: each one now.
    counted = {"kind": "findings", "severity": "high", "count": 2, "params": {}}
    each = [
        {"kind": "finding", "severity": "high", "name": n, "params": {"finding": n}}
        for n in ("a", "b")
    ]
    assert still([counted], each) == (each, 0)
