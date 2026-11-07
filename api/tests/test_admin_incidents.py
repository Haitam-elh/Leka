"""Incidents and the team's notifications in LEKA ADMIN (LEKA-556).

What these protect:
- A problem opens one incident while it is dealt with: a same problem adds
  an occurrence, each fact counted once; three in a day make it recurring,
  its severity raised once; a problem that went is resolved by LEKA, and one
  back afterwards opens a new incident naming the one before.
- The watch reads what LEKA CORE records — a failed intention, an agent
  failing, a source failing, a payment failed, the API's 500s — each incident
  naming its organisation, the demonstration's left out; run again, nothing
  twice; resolved when the problem went.
- The notifications, once each: a critical incident, a payment failed, an
  integration disconnected, errors repeated; each admin reads on their own.
- The routes: filtered lists, a summary, an incident's record and history;
  taken up, given to someone, resolved, taken up again, closed for good, each
  in its history and the admin trail; what an incident cannot become refused.
- An API error is kept by its route as declared, never its values.
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError

from leka.admin import (
    ActivityEvent,
    ActivityWatermark,
    AdminAccount,
    AdminAuditEvent,
    AdminNotification,
    AdminRole,
    Incident,
    IncidentEvent,
)
from leka.admin.incidents import Signal, apply, clear, watch
from leka.api import admin as admin_api
from leka.billing import BillingPayment
from leka.connectors import HealthStatus, Source, SourceKind, SourceStatus
from leka.db import session_factory, system_scope
from leka.ops import drain_api_errors, record_api_error
from tests.test_admin_api import API, NOW, SUPER, World, as_, world  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

OPS = AdminRole.OPERATIONS
FINANCE = AdminRole.FINANCE


async def _incidents(fingerprint: str) -> list[Incident]:
    with system_scope():
        async with session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(Incident)
                        .where(Incident.fingerprint == fingerprint)
                        .order_by(Incident.created_at)
                    )
                ).all()
            )


async def _notifications(incident_id: uuid.UUID) -> list[str]:
    with system_scope():
        async with session_factory() as session:
            return sorted(
                (
                    await session.scalars(
                        select(AdminNotification.kind).where(
                            AdminNotification.incident_id == incident_id
                        )
                    )
                ).all()
            )


async def _applied(*signals: Signal) -> list[str | None]:
    done = []
    with system_scope():
        async with session_factory() as session:
            for signal in signals:
                done.append(await apply(session, signal))
            await session.commit()
    return done


def _signal(world: World, fingerprint: str, key: str | None, **said: Any) -> Signal:
    values: dict[str, Any] = {
        "category": "agent_failed",
        "fingerprint": fingerprint,
        "workspace_id": world.alpha,
        "severity": "medium",
        "at": NOW - timedelta(minutes=30),
        "technical_id": "run-1",
        "detail": {"agent": "code-review"},
        "dedupe_key": key,
    }
    return Signal(**(values | said))


async def test_a_problem_opens_one_incident_counted_once_recurring_on_its_third_time(
    client: AsyncClient, world: World
) -> None:
    fingerprint = f"agent_failed:{world.alpha}:code-review-{world.marker}"
    first = _signal(world, fingerprint, f"t:{world.marker}:1")
    assert await _applied(first, first) == ["opened", None]
    second = _signal(world, fingerprint, f"t:{world.marker}:2", at=NOW - timedelta(minutes=20))
    assert await _applied(second, second) == ["occurred", None]
    [incident] = await _incidents(fingerprint)
    assert (incident.status, incident.occurrences, incident.recurring, incident.severity) == (
        "new",
        2,
        False,
        "medium",
    )
    third = _signal(world, fingerprint, f"t:{world.marker}:3", at=NOW - timedelta(minutes=10))
    assert await _applied(third) == ["occurred"]
    [incident] = await _incidents(fingerprint)
    # Three in a day: recurring, its severity raised one step, once.
    assert (incident.occurrences, incident.recurring, incident.severity) == (3, True, "high")
    assert await _notifications(incident.id) == ["repeated_errors"]
    fourth = _signal(world, fingerprint, f"t:{world.marker}:4", at=NOW - timedelta(minutes=5))
    await _applied(fourth)
    [incident] = await _incidents(fingerprint)
    assert (incident.occurrences, incident.severity) == (4, "high")
    assert await _notifications(incident.id) == ["repeated_errors"]

    # The problem went: resolved by LEKA. Back afterwards: a new incident.
    with system_scope():
        async with session_factory() as session:
            # Not before it was last seen.
            assert not await clear(session, fingerprint, NOW - timedelta(minutes=7), "early")
            assert await clear(session, fingerprint, NOW, "agent_succeeded")
            await session.commit()
    again = _signal(world, fingerprint, f"t:{world.marker}:5", at=NOW + timedelta(minutes=1))
    assert await _applied(again) == ["opened"]
    old, new = await _incidents(fingerprint)
    assert (old.status, new.status, new.previous_id, new.occurrences) == (
        "resolved",
        "new",
        old.id,
        1,
    )
    with system_scope():
        async with session_factory() as session:
            kinds = (
                await session.scalars(
                    select(IncidentEvent.kind)
                    .where(IncidentEvent.incident_id == old.id)
                    .order_by(IncidentEvent.at, IncidentEvent.created_at)
                )
            ).all()
    assert kinds == ["opened", "occurred", "occurred", "recurring", "occurred", "auto_resolved"]


async def test_a_state_opens_once_and_what_is_critical_is_said(
    client: AsyncClient, world: World
) -> None:
    source = f"integration:{uuid.uuid4()}"
    state = _signal(
        world, source, None, category="integration_disconnected", severity="high", detail={}
    )
    # A state still true, read again: never counted again.
    assert await _applied(state, state) == ["opened", None]
    [integration] = await _incidents(source)
    assert integration.occurrences == 1
    assert await _notifications(integration.id) == ["integration_disconnected"]
    rule = f"platform:{world.marker}"
    critical = _signal(
        world, rule, None, category="platform", severity="critical", workspace_id=None
    )
    await _applied(critical)
    [platform] = await _incidents(rule)
    assert platform.for_workspace_id is None
    assert await _notifications(platform.id) == ["critical_incident"]
    invoice = f"payment_failed:in_{world.marker}"
    paid = _signal(
        world, invoice, f"pay:{world.marker}", category="payment_failed", severity="high"
    )
    await _applied(paid)
    [payment] = await _incidents(invoice)
    assert await _notifications(payment.id) == ["payment_failed"]


async def _reset_watermarks() -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                delete(ActivityWatermark).where(ActivityWatermark.source.like("incidents.%"))
            )
            await session.commit()


async def test_the_watch_reads_what_leka_records_once_and_resolves_what_went(
    client: AsyncClient, world: World
) -> None:
    await _reset_watermarks()
    intention = uuid.uuid4()
    failing = Source(
        workspace_id=world.alpha,
        id=uuid.uuid4(),
        kind=SourceKind.AWS,
        name=f"AWS {world.marker}",
        status=SourceStatus.ERROR,
        health_status=HealthStatus.UNHEALTHY,
        last_error={"code": "AUTH_EXPIRED", "message": "The key expired.", "retryable": False},
    )
    with system_scope():
        async with session_factory() as session:
            session.add(failing)
            session.add_all(
                [
                    ActivityEvent(
                        id=uuid.uuid4(),
                        kind="intention.failed",
                        at=NOW - timedelta(minutes=20),
                        for_workspace_id=world.alpha,
                        ref=f"intention:{intention}",
                        dedupe_key=f"intention.failed:{intention}:{world.marker}",
                        properties={},
                    ),
                    *(
                        ActivityEvent(
                            id=uuid.uuid4(),
                            kind="agent_run.failed",
                            at=NOW - timedelta(minutes=15 - n),
                            for_workspace_id=world.alpha,
                            ref=f"agent_run:{uuid.uuid4()}",
                            dedupe_key=f"agent_run:{world.marker}:{n}",
                            properties={"agent": f"review-{world.marker}"},
                        )
                        for n in range(3)
                    ),
                    # The demonstration's: never an incident.
                    ActivityEvent(
                        id=uuid.uuid4(),
                        kind="intention.failed",
                        at=NOW - timedelta(minutes=20),
                        for_workspace_id=world.demo,
                        ref=f"intention:{uuid.uuid4()}",
                        dedupe_key=f"intention.failed:demo:{world.marker}",
                        properties={},
                    ),
                    BillingPayment(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        reference=f"evt_failed_{world.marker}",
                        stripe_invoice_id=f"in_{world.marker}",
                        outcome="failed",
                        amount=17900,
                        currency="eur",
                        attempt=1,
                        at=NOW - timedelta(minutes=10),
                    ),
                ]
            )
            await session.commit()
    await record_api_error(
        method="POST",
        route="/api/v1/intentions/{intention_id}",
        exception="RuntimeError",
        request_id=f"req-{world.marker}",
        workspace_id=world.alpha,
        at=NOW - timedelta(minutes=5),
    )
    await watch(now=NOW)
    expected = {
        f"intention_failed:{intention}": ("intention_failed", 1, False),
        f"agent_failed:{world.alpha}:review-{world.marker}": ("agent_failed", 3, True),
        f"integration:{failing.id}": ("integration_disconnected", 1, False),
        f"payment_failed:in_{world.marker}": ("payment_failed", 1, False),
        f"api_error:{world.alpha}:POST /api/v1/intentions/{{intention_id}}:RuntimeError": (
            "api_error",
            1,
            False,
        ),
    }
    for fingerprint, (category, occurrences, recurring) in expected.items():
        [incident] = await _incidents(fingerprint)
        assert (incident.category, incident.occurrences, incident.recurring) == (
            category,
            occurrences,
            recurring,
        ), fingerprint
        assert incident.for_workspace_id == world.alpha
    [integration] = await _incidents(f"integration:{failing.id}")
    assert integration.detail["code"] == "AUTH_EXPIRED"
    assert integration.detail["source"] == f"AWS {world.marker}"
    with system_scope():
        async with session_factory() as session:
            demo = await session.scalar(
                select(func.count()).where(Incident.for_workspace_id == world.demo)
            )
    assert demo == 0

    # Run again: nothing twice.
    await watch(now=NOW + timedelta(minutes=5))
    for fingerprint, (_, occurrences, _) in expected.items():
        [incident] = await _incidents(fingerprint)
        assert incident.occurrences == occurrences, fingerprint

    # The problems went: the intention completed, the agent succeeded, the
    # source healthy again.
    with system_scope():
        async with session_factory() as session:
            session.add_all(
                [
                    ActivityEvent(
                        id=uuid.uuid4(),
                        kind="intention.completed",
                        at=NOW + timedelta(minutes=6),
                        for_workspace_id=world.alpha,
                        ref=f"intention:{intention}",
                        dedupe_key=f"intention.completed:{intention}:{world.marker}",
                        properties={},
                    ),
                    ActivityEvent(
                        id=uuid.uuid4(),
                        kind="agent_run.succeeded",
                        at=NOW + timedelta(minutes=6),
                        for_workspace_id=world.alpha,
                        ref=f"agent_run:{uuid.uuid4()}",
                        dedupe_key=f"agent_run:{world.marker}:ok",
                        properties={"agent": f"review-{world.marker}"},
                    ),
                ]
            )
            source = await session.get(Source, failing.id)
            assert source is not None
            source.status = SourceStatus.ACTIVE
            source.health_status = HealthStatus.HEALTHY
            await session.commit()
    await watch(now=NOW + timedelta(minutes=10))
    for fingerprint in (
        f"intention_failed:{intention}",
        f"agent_failed:{world.alpha}:review-{world.marker}",
        f"integration:{failing.id}",
    ):
        [incident] = await _incidents(fingerprint)
        assert incident.status == "resolved", fingerprint
    [payment] = await _incidents(f"payment_failed:in_{world.marker}")
    assert payment.status == "new"


async def _incident(world: World, **said: Any) -> Incident:
    fingerprint = f"api_error:{world.alpha}:GET /x:{world.marker}:{uuid.uuid4()}"
    await _applied(
        _signal(
            world,
            fingerprint,
            f"api:{uuid.uuid4()}",
            category="api_error",
            severity="high",
            detail={"method": "GET", "route": "/x", "exception": "RuntimeError"},
            **said,
        )
    )
    [incident] = await _incidents(fingerprint)
    return incident


async def _admin_id(world: World, role: AdminRole) -> uuid.UUID:
    async with session_factory() as session:
        found = await session.scalar(
            select(AdminAccount.id).where(
                AdminAccount.email == f"{role.value}-{world.marker}@leka.test"
            )
        )
    assert found is not None
    return found


async def test_an_incident_dealt_with_each_step_in_its_history_and_the_trail(
    client: AsyncClient, world: World
) -> None:
    incident = await _incident(world)
    url = f"{API}/incidents/{incident.id}"
    me = await _admin_id(world, OPS)

    taken = await client.patch(
        url,
        json={"status": "in_progress", "assignee_id": str(me), "note": "Looking at the logs."},
        headers=as_(world, OPS),
    )
    assert taken.status_code == 200, taken.text
    said = taken.json()
    assert (said["incident"]["status"], said["incident"]["assignee"]["id"]) == (
        "in_progress",
        str(me),
    )
    assert [e["kind"] for e in said["history"]][:3] == ["note", "status", "assigned"]
    assert said["history"][0]["detail"] == {"note": "Looking at the logs."}
    assert said["history"][0]["by"] == f"operations-{world.marker}@leka.test"

    mine = await client.get(
        f"{API}/incidents", params={"mine": "true", "limit": 200}, headers=as_(world, OPS)
    )
    assert str(incident.id) in {r["id"] for r in mine.json()["data"]}

    resolved = await client.patch(url, json={"status": "resolved"}, headers=as_(world, OPS))
    assert resolved.json()["incident"]["resolved_at"] is not None
    # Taken up again, then closed for good.
    again = await client.patch(url, json={"status": "in_progress"}, headers=as_(world, OPS))
    assert again.json()["incident"]["resolved_at"] is None
    closed = await client.patch(url, json={"status": "closed"}, headers=as_(world, OPS))
    assert closed.json()["incident"]["status"] == "closed"
    final = await client.patch(url, json={"status": "in_progress"}, headers=as_(world, OPS))
    assert final.status_code == 422

    async with session_factory() as session:
        trail = (
            await session.scalars(
                select(AdminAuditEvent.detail).where(
                    AdminAuditEvent.action == "admin.incident_updated",
                    AdminAuditEvent.target_id == str(incident.id),
                )
            )
        ).all()
    # Four changes; the note said, never its words.
    assert len(trail) == 4
    assert any(d.get("note") is True for d in trail)
    assert all("Looking at the logs." not in str(d) for d in trail)


async def test_what_an_incident_cannot_take_is_refused(client: AsyncClient, world: World) -> None:
    incident = await _incident(world)
    url = f"{API}/incidents/{incident.id}"
    assert (await client.patch(url, json={}, headers=as_(world, OPS))).status_code == 422
    assert (
        await client.patch(url, json={"status": "new"}, headers=as_(world, OPS))
    ).status_code == 422
    nobody = await client.patch(
        url, json={"assignee_id": str(uuid.uuid4())}, headers=as_(world, OPS)
    )
    assert nobody.status_code == 422
    # Finance reads, does not deal with incidents.
    assert (await client.get(url, headers=as_(world, FINANCE))).status_code == 200
    refused = await client.patch(url, json={"status": "resolved"}, headers=as_(world, FINANCE))
    assert refused.status_code == 403
    missing = await client.get(f"{API}/incidents/{uuid.uuid4()}", headers=as_(world, OPS))
    assert missing.status_code == 404

    # Resolved, then the same problem again: taking the old one up is refused.
    await client.patch(url, json={"status": "resolved"}, headers=as_(world, OPS))
    await _applied(
        _signal(
            world,
            incident.fingerprint,
            f"api:{uuid.uuid4()}",
            category="api_error",
            severity="high",
            at=NOW + timedelta(minutes=1),
        )
    )
    conflict = await client.patch(url, json={"status": "in_progress"}, headers=as_(world, OPS))
    assert conflict.status_code == 409


async def test_incidents_listed_with_their_filters_and_counted(
    client: AsyncClient, world: World
) -> None:
    incident = await _incident(world)
    listed = await client.get(
        f"{API}/incidents",
        params={
            "organisation_id": str(world.alpha),
            "category": "api_error",
            "status": ["new", "in_progress"],
            "severity": "high",
            "limit": 200,
        },
        headers=as_(world, SUPER),
    )
    assert listed.status_code == 200, listed.text
    row = next(r for r in listed.json()["data"] if r["id"] == str(incident.id))
    assert row["organisation"] == {"id": str(world.alpha), "name": f"Alpha {world.marker}"}
    assert (row["number"], row["category"], row["severity"], row["status"]) == (
        incident.number,
        "api_error",
        "high",
        "new",
    )
    by_number = await client.get(
        f"{API}/incidents", params={"number": incident.number}, headers=as_(world, SUPER)
    )
    assert [r["id"] for r in by_number.json()["data"]] == [str(incident.id)]
    resolved_only = await client.get(
        f"{API}/incidents",
        params={"status": "resolved", "organisation_id": str(world.alpha)},
        headers=as_(world, SUPER),
    )
    assert str(incident.id) not in {r["id"] for r in resolved_only.json()["data"]}
    summary = (await client.get(f"{API}/incidents/summary", headers=as_(world, SUPER))).json()
    assert summary["open"] >= 1 and summary["by_category"]["api_error"] >= 1
    assert set(summary["by_status"]) == {"new", "in_progress"}
    assert set(summary["by_severity"]) == {"critical", "high", "medium", "low"}
    people = (await client.get(f"{API}/incidents/assignees", headers=as_(world, SUPER))).json()
    assert f"operations-{world.marker}@leka.test" in {p["email"] for p in people}


async def test_notifications_read_by_each_admin_on_their_own(
    client: AsyncClient, world: World
) -> None:
    rule = f"platform:{world.marker}"
    await _applied(_signal(world, rule, None, category="platform", severity="critical"))
    [incident] = await _incidents(rule)
    listed = await client.get(
        f"{API}/notifications", params={"unread": "true", "limit": 200}, headers=as_(world, OPS)
    )
    mine = next(n for n in listed.json()["data"] if n["incident_id"] == str(incident.id))
    assert (mine["kind"], mine["severity"], mine["read_at"], mine["incident_number"]) == (
        "critical_incident",
        "critical",
        None,
        incident.number,
    )
    before = (await client.get(f"{API}/notifications/unread", headers=as_(world, OPS))).json()
    read = await client.post(
        f"{API}/notifications/read",
        json={"ids": [mine["id"], str(uuid.uuid4())]},
        headers=as_(world, OPS),
    )
    assert read.json() == {"unread": before["unread"] - 1, "marked": 1}
    again = await client.post(
        f"{API}/notifications/read", json={"ids": [mine["id"]]}, headers=as_(world, OPS)
    )
    assert again.json()["marked"] == 0
    # Another admin has not read it.
    theirs = await client.get(
        f"{API}/notifications", params={"unread": "true", "limit": 200}, headers=as_(world, SUPER)
    )
    assert mine["id"] in {n["id"] for n in theirs.json()["data"]}
    every = await client.post(
        f"{API}/notifications/read", json={"every": True}, headers=as_(world, SUPER)
    )
    assert every.json()["unread"] == 0
    assert (
        await client.post(f"{API}/notifications/read", json={}, headers=as_(world, SUPER))
    ).status_code == 422


async def test_an_api_error_is_kept_by_its_route_never_its_values(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    await drain_api_errors()

    async def broken(*_: object) -> None:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(admin_api, "incidents_summary", broken)
    with pytest.raises(RuntimeError):
        await client.get(f"{API}/incidents/summary", headers=as_(world, SUPER))
    kept = await drain_api_errors()
    assert kept is not None
    [said] = [k for k in kept if k["route"] == "/api/v1/admin/incidents/summary"]
    assert (said["method"], said["exception"], said["workspace_id"]) == (
        "GET",
        "RuntimeError",
        None,
    )
    assert said["request_id"]
    assert "the database went away" not in str(said)


async def test_an_incident_s_history_is_never_changed(client: AsyncClient, world: World) -> None:
    incident = await _incident(world)
    with system_scope():
        async with session_factory() as session:
            event = await session.scalar(
                select(IncidentEvent).where(IncidentEvent.incident_id == incident.id)
            )
            assert event is not None
            event.detail = {"rewritten": True}
            with pytest.raises(DBAPIError, match="append-only"):
                await session.commit()
