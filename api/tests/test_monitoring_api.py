"""The Digital Twin and its watch (LEKA-442), on the demo company.

What these protect:
- the environment says each thing's state with where it comes from — a
  service Datadog watches, read recently: operational, measured, from
  acme-eu; one nothing says anything of: unknown, never operational — the
  sources each in their state (a failing one « error », one never read
  « never »), how fresh (read every hour, not in real time), what covers
  each part; a thing's sheet, its sources;
- Free: everything seen, no alert opened — the plan that would, said;
- Growth: an incident opened on payment-api opens one alert, confirmed, and
  a failing source one more; told once by e-mail; seen again, never a
  second; the incident closed and Datadog read since: resolved, said by
  what; the failing source, still open;
- Starter: alerted in LEKA, never by e-mail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import set_plan
from leka.identity import EmailMessage, User
from leka.ingestion import ResolvedEntity
from leka.monitoring import AlertRepository, watch
from leka.monitoring import service as monitoring_service
from leka.platform import Workspace
from tests.conftest import FakeIdentity
from tests.test_intention_benchmark import _seed_module

pytestmark = pytest.mark.integration

ENVIRONMENT = "/api/v1/ingestion/enrichment/environment"


class Outbox:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(monitoring_service, "build_email_sender", lambda: box)
    return box


async def demo(identity: FakeIdentity) -> uuid.UUID:
    seed = _seed_module()
    await seed.seed()
    with system_scope():
        async with session_factory() as session:
            workspace = await session.scalar(select(Workspace).where(Workspace.slug == "acme"))
            nora = await session.scalar(select(User).where(User.email == seed.DEMO_EMAIL))
    assert workspace is not None and nora is not None
    identity.sign_in(nora.id, workspace.id)
    return workspace.id


async def plan(workspace_id: uuid.UUID, name: str) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            await set_plan(session, workspace_id, name, by="test", reason="LEKA-442")
            await session.commit()


async def incident(workspace_id: uuid.UUID, state: str) -> None:
    """OPS-1841, the demo's incident on payment-api, opened or closed."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            row = await session.scalar(
                select(ResolvedEntity).where(
                    ResolvedEntity.workspace_id == workspace_id, ResolvedEntity.key == "OPS-1841"
                )
            )
            assert row is not None
            row.attributes = {**row.attributes, "state": state}
            await session.commit()


async def alerts(workspace_id: uuid.UUID) -> list[Any]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            return list(
                await AlertRepository(session, workspace_id).lately(
                    datetime(2000, 1, 1, tzinfo=UTC)
                )
            )


async def test_the_twin_says_each_state_where_it_comes_from_and_how_fresh(
    client: AsyncClient, identity: FakeIdentity
) -> None:
    await demo(identity)
    env = (await client.get(ENVIRONMENT)).json()
    nodes = {n["name"]: n for n in env["nodes"]}
    payment = nodes["payment-api"]["twin"]
    assert (payment["state"], payment["basis"], payment["reason"]) == (
        "operational",
        "measured",
        "monitored_quiet",
    )
    assert payment["signal"] == ["acme-eu"] and payment["fresh"]
    auth = nodes["auth-service"]["twin"]
    # Nothing says how it is: unknown — never « sain ».
    assert (auth["state"], auth["reason"]) == ("unknown", "no_signal")
    assert nodes["acme/backend"]["twin"] is None
    assert env["states"]["operational"] == 1 and env["states"]["unknown"] >= 1
    sources = {s["name"]: s for s in env["sources"]}
    assert sources["Runbooks space"]["state"] == "error"
    assert sources["#platform"]["state"] == "never"
    assert sources["acme-eu"]["state"] == "read"
    fresh = env["freshness"]
    assert (fresh["every_minutes"], fresh["late"], fresh["webhooks"]) == (60, False, False)
    parts = {c["part"]: c for c in env["coverage"]}
    assert parts["health"]["covered"] and sources["acme-eu"]["id"] in parts["health"]["sources"]
    sheet = (await client.get(f"{ENVIRONMENT}/{nodes['payment-api']['entity_id']}")).json()
    assert sheet["twin"]["state"] == "operational"
    assert {s["name"] for s in sheet["sources"]} == {"acme/backend", "acme-eu"}


async def test_free_sees_everything_and_is_never_alerted(
    client: AsyncClient, identity: FakeIdentity, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await incident(workspace_id, "open")
    read = (await client.get("/api/v1/monitoring")).json()
    assert read["entitlement"] == {
        "plan": "free",
        "proactive": False,
        "alerts": [],
        "contractual": False,
        "provisional": True,
        "alerts_from": "starter",
        "email_from": "growth",
    }
    assert read["open"] == []
    assert await watch(workspace_id, datetime.now(UTC)) == 0
    assert await alerts(workspace_id) == []
    # The state itself is seen all the same: payment-api degraded.
    env = (await client.get(ENVIRONMENT)).json()
    payment = next(n for n in env["nodes"] if n["name"] == "payment-api")["twin"]
    assert (payment["state"], payment["incident"]["key"]) == ("degraded", "OPS-1841")
    assert outbox.sent == []


async def test_a_paid_plan_is_alerted_once_and_resolved_only_by_a_signal(
    client: AsyncClient, identity: FakeIdentity, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    await incident(workspace_id, "open")
    assert await watch(workspace_id, datetime.now(UTC)) == 2
    read = (await client.get("/api/v1/monitoring")).json()
    assert read["entitlement"]["alerts"] == ["in_app", "email"]
    by_subject = {a["subject_name"]: a for a in read["open"]}
    payment = by_subject["payment-api"]
    assert (payment["kind"], payment["severity"], payment["certainty"]) == (
        "degraded",
        "medium",
        "confirmed",
    )
    assert payment["detail"]["incident"]["key"] == "OPS-1841"
    assert by_subject["Runbooks space"]["kind"] == "source_failing"
    [told] = outbox.sent
    assert told.to == "nora@acme.example" and "payment-api" in told.body
    # Seen again: never a second alert, never told twice.
    assert await watch(workspace_id, datetime.now(UTC)) == 0
    assert len(await alerts(workspace_id)) == 2 and len(outbox.sent) == 1
    # Closed, and Datadog read since: resolved, said by what.
    await incident(workspace_id, "closed")
    await watch(workspace_id, datetime.now(UTC))
    ended = {a.subject_name: a for a in await alerts(workspace_id)}
    assert ended["payment-api"].status == "resolved"
    assert ended["payment-api"].resolution["signal"] == ["acme-eu"]
    assert ended["Runbooks space"].status == "open"


async def test_starter_is_alerted_in_leka_never_by_email(
    client: AsyncClient, identity: FakeIdentity, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "starter")
    await incident(workspace_id, "open")
    assert await watch(workspace_id, datetime.now(UTC)) == 2
    read = (await client.get("/api/v1/monitoring")).json()
    assert read["entitlement"]["alerts"] == ["in_app"]
    assert len(read["open"]) == 2
    assert outbox.sent == []
