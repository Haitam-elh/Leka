"""The notification centre (LEKA-476), end to end.

What these protect, family by family — each told only from what its own
system kept, to whom it concerns:
- Intentions: their asker told it was asked, analysed, needs them; a
  decision told to who may decide too; nobody else.
- Agents: who ran one told it ended, and how.
- Monitoring: every member told an alert opened, was taken in hand, ended,
  opened again.
- Sources: who manages them told a read failed, came back, a source was
  lost, its data went stale — once per stretch.
- Billing: who pays told what Stripe confirmed — a plan changed, a
  cancellation scheduled, a payment failed, a renewal; every member told
  a share of the credits passed.
- The workspace: a person told their role changed; who invites told
  someone joined.
And for the centre itself: read and unread kept, all read at once, muted by
category; each fact told once, however often read; another workspace sees
nothing, an empty centre says so; a family that fails is said and the
others read; a page at a time, a cursor not its own refused.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from leka.billing import StripeEvent
from leka.capabilities import AgentRun
from leka.db import Base, session_factory, system_scope, workspace_scope
from leka.governance import AuditEvent
from leka.intentions.processing import analyse_intention
from leka.metering import CreditWarning
from leka.monitoring import MonitoringAlert
from leka.notifications import Notification, NotificationCursor, project
from leka.notifications.projector import FAMILIES, Read
from tests.conftest import FakeIdentity
from tests.test_billing_stripe import (
    API as BILLING,
)
from tests.test_billing_stripe import (
    FakeStripe,
    _deliver,
    _event,
    _synced,
    stripe,
    subscription,
)
from tests.test_context_engine import model
from tests.test_intention_analysis_api import queued  # noqa: F401 — a fixture
from tests.test_sources_api import _as, _create, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = (model, stripe)  # fixtures, requested by name
API = "/api/v1/notifications"
ASKED = "Qui est responsable de Billing API ?"


async def _centre(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(API, params=params)
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()
    return page


async def _kinds(client: AsyncClient, **params: Any) -> list[str]:
    return [n["kind"] for n in (await _centre(client, **params))["data"]]


async def _unread(client: AsyncClient) -> int:
    response = await client.get(f"{API}/unread")
    assert response.status_code == 200, response.text
    return int(response.json()["unread"])


async def _kept(workspace_id: uuid.UUID, *rows: Base) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            session.add_all(rows)
            await session.commit()


def _alert(workspace_id: uuid.UUID, subject: uuid.UUID, **values: Any) -> MonitoringAlert:
    now = datetime.now(UTC)
    fields: dict[str, Any] = {
        "subject_type": "entity",
        "subject_id": subject,
        "subject_name": "payment-api",
        "family": "health",
        "kind": "unavailable",
        "severity": "high",
        "certainty": "confirmed",
        "status": "open",
        "opened_at": now,
        "last_seen_at": now,
    }
    return MonitoringAlert(workspace_id=workspace_id, id=uuid.uuid4(), **(fields | values))


def _warning(workspace_id: uuid.UUID, threshold: int = 80) -> CreditWarning:
    return CreditWarning(
        workspace_id=workspace_id,
        id=uuid.uuid4(),
        period=datetime.now(UTC).date().replace(day=1),
        threshold=threshold,
        credits=1000,
        used=float(threshold * 10),
        at=datetime.now(UTC),
    )


# ── each family ──────────────────────────────────────────────────────────────


async def test_an_intention_told_to_its_asker_a_decision_to_who_may_decide(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    asked = await client.post("/api/v1/intentions", json={"text": ASKED})
    assert asked.status_code == 201, asked.text
    intention = asked.json()["intention"]["id"]
    told = {(n["kind"], n["link"]) for n in (await _centre(client))["data"]}
    assert ("intention.created", f"/intentions/{intention}") in told
    assert ("intention.analysis_started", f"/intentions/{intention}") in told
    # Not theirs: another member's question.
    _as(identity, acme, "admin")
    assert not [k for k in await _kinds(client) if k.startswith("intention.")]

    await analyse_intention(acme["acme"], uuid.UUID(intention), trigger="created")
    # Who may decide is told it waits for a decision — on its decision.
    deciding = [
        n for n in (await _centre(client))["data"] if n["kind"] == "intention.decision_required"
    ]
    assert [(n["link"], n["severity"], n["params"]["title"]) for n in deciding] == [
        (f"/intentions/{intention}/decision", "warning", ASKED)
    ]
    _as(identity, acme, "member")
    assert "intention.decision_required" in await _kinds(client)


async def test_an_agent_run_ended_told_to_who_ran_it(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    now = datetime.now(UTC)
    run = AgentRun(
        workspace_id=acme["acme"],
        id=uuid.uuid4(),
        key="code-review",
        version="1.3.0",
        status="succeeded",
        requested_by=acme["member"],
        format="markdown",
        queued_at=now,
        finished_at=now,
    )
    await _kept(acme["acme"], run)
    _as(identity, acme, "member")
    [told] = [n for n in (await _centre(client))["data"] if n["category"] == "agent"]
    assert (told["kind"], told["severity"], told["link"], told["params"]["agent"]) == (
        "agent.run_succeeded",
        "success",
        "/capabilities/code-review",
        "Revue de code",
    )
    _as(identity, acme, "admin")
    assert "agent.run_succeeded" not in await _kinds(client)


async def test_an_alerts_life_told_to_every_member(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    subject = uuid.uuid4()
    first = _alert(acme["acme"], subject, opened_at=datetime.now(UTC) - timedelta(hours=3))
    await _kept(acme["acme"], first)
    _as(identity, acme, "member")
    [opened] = [n for n in (await _centre(client))["data"] if n["category"] == "monitoring"]
    assert (opened["kind"], opened["severity"], opened["params"]["name"]) == (
        "alert.triggered",
        "critical",
        "payment-api",
    )
    # Taken in hand, then ended by a fresh signal.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            row = await session.get(MonitoringAlert, first.id)
            assert row is not None
            row.acknowledged_at = datetime.now(UTC) - timedelta(hours=2)
            row.acknowledged_by = acme["admin"]
            row.status = "resolved"
            row.resolved_at = datetime.now(UTC) - timedelta(hours=1)
            await session.commit()
    # The same thing in the same trouble again: opened again.
    await _kept(acme["acme"], _alert(acme["acme"], subject))
    _as(identity, acme, "admin")
    kinds = await _kinds(client, category="monitoring")
    assert sorted(kinds) == [
        "alert.acknowledged",
        "alert.reopened",
        "alert.resolved",
        "alert.triggered",
    ]


async def test_sources_told_to_who_manages_them_their_staleness_once(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    from leka.connectors import Source, SourceEvent, SourceEventType, SourceStatus

    _as(identity, acme, "admin")
    source = uuid.UUID((await _create(client))["id"])
    events = [
        SourceEvent(
            workspace_id=acme["acme"],
            id=uuid.uuid4(),
            source_id=source,
            type=kind,
            payload=payload,
        )
        for kind, payload in (
            (SourceEventType.SYNC_FAILED, {"code": "auth_failed"}),
            (SourceEventType.SYNC_RECOVERED, {}),
            (SourceEventType.HEALTH_CHANGED, {"previous": "healthy", "current": "unhealthy"}),
        )
    ]
    await _kept(acme["acme"], *events)
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            row = await session.get(Source, source)
            assert row is not None
            row.status = SourceStatus.ACTIVE
            row.last_synced_at = datetime.now(UTC) - timedelta(hours=5)
            await session.commit()
    kinds = await _kinds(client, category="source")
    assert sorted(kinds) == [
        "source.disconnected",
        "source.stale",
        "source.sync_failed",
        "source.sync_recovered",
    ]
    # Stale since the same read: told once, however often looked at.
    assert (await _kinds(client, category="source")).count("source.stale") == 1
    _as(identity, acme, "member")
    assert await _kinds(client, category="source") == []


async def test_billing_as_stripe_confirmed_it_told_to_who_pays_the_credits_to_all(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    workspace = acme["acme"]
    await _synced(stripe)
    _as(identity, acme, "admin")
    assert (
        await client.post(f"{BILLING}/checkout", json={"plan": "growth", "interval": "month"})
    ).status_code == 200
    stripe.subscriptions["sub_1"] = subscription("growth", "active")
    completed = _event(
        "checkout.session.completed",
        {
            "id": "cs_1",
            "mode": "subscription",
            "subscription": "sub_1",
            "customer": "cus_1",
            "client_reference_id": str(workspace),
        },
        created=1_800_000_100,
    )
    assert (await _deliver(client, completed)).json() == {"received": "plan:growth"}
    cancelling = subscription("growth", "active") | {"cancel_at_period_end": True}
    assert (
        await _deliver(
            client, _event("customer.subscription.updated", cancelling, created=1_800_000_200)
        )
    ).json() == {"received": "plan:growth"}
    failed = _event(
        "invoice.payment_failed", {"customer": "cus_1", "id": "in_1"}, created=1_800_000_300
    )
    assert (await _deliver(client, failed)).status_code == 200
    renewed = _event(
        "invoice.paid",
        {"customer": "cus_1", "id": "in_2", "billing_reason": "subscription_cycle"},
        created=1_800_000_400,
    )
    assert (await _deliver(client, renewed)).status_code == 200
    await _kept(workspace, _warning(workspace))

    told = {n["kind"]: n for n in (await _centre(client, category="billing"))["data"]}
    assert set(told) == {
        "billing.plan_changed",
        "billing.cancellation_scheduled",
        "billing.payment_failed",
        "billing.renewed",
        "capacity.threshold",
    }
    assert (
        told["billing.plan_changed"]["params"]["before"],
        told["billing.plan_changed"]["params"]["after"],
    ) == (
        "free",
        "growth",
    )
    assert told["billing.payment_failed"]["severity"] == "critical"
    # Every member is told of the credits; the rest is who pays'.
    _as(identity, acme, "member")
    assert await _kinds(client, category="billing") == ["capacity.threshold"]
    # A Stripe event not applied tells nothing.
    with system_scope():
        async with session_factory() as session:
            assert await session.scalar(
                select(func.count())
                .select_from(StripeEvent)
                .where(StripeEvent.outcome == "applied")
            )


async def test_the_workspace_a_role_told_to_its_member_a_newcomer_to_who_invites(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    now = datetime.now(UTC)

    def audit(action: str, target: uuid.UUID, **detail: Any) -> AuditEvent:
        return AuditEvent(
            workspace_id=acme["acme"],
            id=uuid.uuid4(),
            at=now,
            category="team",
            action=action,
            outcome="success",
            actor_type="user",
            actor_id=acme["admin"],
            target_type="user",
            target_id=str(target),
            target_label="Camille Martin",
            detail=detail,
        )

    await _kept(
        acme["acme"],
        audit("member.role_changed", acme["member"], before="member", after="admin"),
        audit("member.joined", uuid.uuid4()),
    )
    _as(identity, acme, "member")
    [changed] = (await _centre(client, category="workspace"))["data"]
    assert (changed["kind"], changed["params"]) == (
        "workspace.role_changed",
        {"before": "member", "after": "admin"},
    )
    _as(identity, acme, "admin")
    [joined] = (await _centre(client, category="workspace"))["data"]
    assert (joined["kind"], joined["params"]["name"]) == (
        "workspace.member_joined",
        "Camille Martin",
    )


# ── the centre ───────────────────────────────────────────────────────────────


async def test_read_and_unread_kept_all_read_at_once_and_categories_muted(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _kept(workspace, _warning(workspace), _alert(workspace, uuid.uuid4()))
    _as(identity, acme, "member")
    assert await _unread(client) == 2
    first = (await _centre(client))["data"][0]
    assert (await client.post(f"{API}/{first['id']}/read")).status_code == 204
    assert await _unread(client) == 1
    assert next(n for n in (await _centre(client))["data"] if n["id"] == first["id"])["read"]
    assert [n["id"] for n in (await _centre(client, unread=True))["data"]] != [first["id"]]
    assert (await client.delete(f"{API}/{first['id']}/read")).status_code == 204
    assert await _unread(client) == 2
    # Someone else's read state is theirs.
    marked = await client.post(f"{API}/read", json={})
    assert marked.json() == {"marked": 2}
    assert await _unread(client) == 0
    _as(identity, acme, "admin")
    assert await _unread(client) == 2

    # Muted: not shown, not counted — and said back.
    muted = await client.put(f"{API}/preferences", json={"muted": ["billing"]})
    assert muted.json() == {"muted": ["billing"]}
    assert (await client.get(f"{API}/preferences")).json() == {"muted": ["billing"]}
    assert await _unread(client) == 1
    assert "capacity.threshold" not in await _kinds(client)
    await client.put(f"{API}/preferences", json={"muted": []})
    assert await _unread(client) == 2
    # Not one of theirs: 404.
    assert (await client.post(f"{API}/{uuid.uuid4()}/read")).status_code == 404


async def test_each_fact_told_once_however_often_read(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _kept(workspace, _warning(workspace), _alert(workspace, uuid.uuid4()))
    _as(identity, acme, "member")
    for _ in range(3):
        await _centre(client)
        await _unread(client)
    with workspace_scope(workspace):
        async with session_factory() as session:
            assert await project(session, workspace) == 0
            kept = await session.scalar(select(func.count()).select_from(Notification))
            assert kept == 2


async def test_another_workspace_sees_none_and_an_empty_centre_says_so(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _kept(workspace, _warning(workspace), _alert(workspace, uuid.uuid4()))
    _as(identity, acme, "other_admin")
    assert await _centre(client) == {"data": [], "next_cursor": None, "unread": 0}
    assert await _unread(client) == 0


async def test_a_family_that_fails_is_said_and_the_others_read(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    await _kept(workspace, _warning(workspace))

    async def broken(*_: Any) -> Read:
        raise RuntimeError("its table is gone")

    with workspace_scope(workspace):
        async with session_factory() as session:
            told = await project(
                session, workspace, families={"broken": broken, "credits": FAMILIES["credits"]}
            )
            await session.commit()
        async with session_factory() as session:
            cursors = {
                c.family: c for c in (await session.scalars(select(NotificationCursor))).all()
            }
    assert told == 1
    assert cursors["broken"].failure == "RuntimeError: its table is gone"
    assert cursors["broken"].failed_at is not None
    assert cursors["credits"].failure is None


async def test_a_page_at_a_time_and_a_cursor_not_its_own_refused(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    now = datetime.now(UTC)
    await _kept(
        workspace,
        *[_alert(workspace, uuid.uuid4(), opened_at=now - timedelta(minutes=i)) for i in range(3)],
    )
    _as(identity, acme, "member")
    first = await _centre(client, limit=2)
    assert len(first["data"]) == 2 and first["next_cursor"]
    second = await _centre(client, limit=2, cursor=first["next_cursor"])
    assert len(second["data"]) == 1 and second["next_cursor"] is None
    assert {n["id"] for n in first["data"]}.isdisjoint({n["id"] for n in second["data"]})
    # The latest first.
    times = [n["occurred_at"] for n in first["data"] + second["data"]]
    assert times == sorted(times, reverse=True)
    assert (await client.get(API, params={"cursor": "not-a-cursor"})).status_code == 400
