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

from leka.capabilities import CodeChange
from leka.connectors import Source, SourceStatus
from leka.db import session_factory, system_scope, workspace_scope
from leka.monitoring import MonitoringAlert, NightReview
from leka.monitoring.night import review_every_workspace
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_sources_api import _as, _create, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/monitoring/night-review"


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
