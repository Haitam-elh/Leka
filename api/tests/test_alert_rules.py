"""The alerts a person sets on Mon environnement (LEKA-477), on the demo
company — its incident OPS-1841 on payment-api, Datadog (acme-eu) reading it.

What these protect:
- What may be watched is what a source reads, with a known freshness:
  payment-api (unavailable, degraded), a connected source (failing) — never
  auth-service, whose state nothing says. Every channel said where it
  stands: in-app operational, e-mail untested until a delivery went, SMS,
  WhatsApp, Slack, Teams, Discord unavailable; e-mail not in Starter.
- Checked by the server: the subject watched, its conditions, the channels,
  the recipients members, the plan's limit (Free: none — Starter named; at
  Starter's five, the sixth refused); who manages the sources only.
- Told once per episode — the same alert seen again, never twice; after its
  confirmation delay only; again every `repeat_hours` until taken in hand;
  never on stale data.
- A failed delivery kept and said, the channel then « failing »; a test
  tries each channel now.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.db import session_factory, system_scope, workspace_scope
from leka.identity import EmailMessage, User
from leka.monitoring import AlertDelivery, MonitoringAlert, watch
from leka.monitoring import rules as monitoring_rules
from leka.monitoring import service as monitoring_service
from leka.platform import Membership, Role
from tests.conftest import FakeIdentity
from tests.test_monitoring_api import Outbox, _nora, demo, incident, plan

pytestmark = pytest.mark.integration

RULES = "/api/v1/monitoring/rules"


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(monitoring_service, "build_email_sender", lambda: box)
    monkeypatch.setattr(monitoring_rules, "build_email_sender", lambda: box)
    return box


class Refusing:
    async def send(self, message: EmailMessage) -> None:
        raise ConnectionError("smtp down")


async def _subject(client: AsyncClient, name: str) -> dict[str, Any]:
    read = (await client.get(RULES)).json()
    return next(w for w in read["watchable"] if w["name"] == name)


async def _rule(client: AsyncClient, **over: Any) -> Any:
    payment = await _subject(client, "payment-api")
    body = {
        "name": "payment-api en panne",
        "subject_type": "entity",
        "subject_id": payment["subject_id"],
        "conditions": ["degraded", "unavailable"],
        "severity": "high",
        "channels": ["in_app", "email"],
        "recipients": [str(await _nora())],
        **over,
    }
    return await client.post(RULES, json=body)


async def _deliveries(workspace_id: uuid.UUID) -> list[AlertDelivery]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            return list((await session.scalars(select(AlertDelivery))).all())


def _rule_mails(outbox: Outbox) -> list[EmailMessage]:
    return [m for m in outbox.sent if "« payment-api en panne »" in m.subject]


async def test_what_may_be_watched_and_how_each_channel_stands(
    client: AsyncClient, identity: FakeIdentity, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    read = (await client.get(RULES)).json()
    assert (read["limit"], read["used"], read["upgrade"]) == (20, 0, None)
    names = {w["name"]: w for w in read["watchable"]}
    assert names["payment-api"]["conditions"] == ["unavailable", "degraded"]
    assert names["acme-eu"]["conditions"] == ["source_failing"]
    # Nothing says how auth-service is: no rule on it.
    assert "auth-service" not in names
    assert {c["key"]: c["status"] for c in read["channels"]} == {
        "in_app": "operational",
        "email": "untested",
        "sms": "unavailable",
        "whatsapp": "unavailable",
        # Connected by a webhook (LEKA-496): not yet here.
        "slack": "not_connected",
        "teams": "not_connected",
        "discord": "not_connected",
    }
    await plan(workspace_id, "starter")
    channels = {c["key"]: c["status"] for c in (await client.get(RULES)).json()["channels"]}
    assert channels["email"] == "not_in_plan"


async def test_checked_by_the_server_never_trusted_from_a_screen(
    client: AsyncClient, identity: FakeIdentity, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    env = (await client.get("/api/v1/ingestion/enrichment/environment")).json()
    auth = next(n for n in env["nodes"] if n["name"] == "auth-service")

    def why(response: Any) -> str:
        assert response.status_code == 422, response.text
        return str(response.json()["error"]["details"][0]["message"])

    assert why(await _rule(client, subject_id=auth["entity_id"])) == "not_watched"
    assert why(await _rule(client, conditions=["source_failing"])) == "condition_unavailable"
    assert why(await _rule(client, channels=["slack"])) == "channel_unavailable"
    assert why(await _rule(client, recipients=[])) == "not_a_member"
    assert why(await _rule(client, recipients=[str(uuid.uuid4())])) == "not_a_member"
    # In LEKA only, nobody to e-mail: fine.
    assert (await _rule(client, channels=["in_app"], recipients=[])).status_code == 201

    # E-mail is not in Starter.
    await plan(workspace_id, "starter")
    assert why(await _rule(client)) == "channel_unavailable"

    # A member reads them, and may not set one.
    with system_scope():
        async with session_factory() as session:
            member = User(email=f"member-{uuid.uuid4().hex[:8]}@acme.example")
            session.add(member)
            await session.flush()
            session.add(Membership(workspace_id=workspace_id, user_id=member.id, role=Role.MEMBER))
            await session.commit()
            member_id = member.id
    identity.sign_in(member_id, workspace_id)
    assert (await client.get(RULES)).status_code == 200
    assert (await _rule(client, channels=["in_app"])).status_code == 403


async def test_the_plans_limit_free_none_starter_five(
    client: AsyncClient, identity: FakeIdentity, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "free")
    refused = await _rule(client, channels=["in_app"])
    # On Free nothing is watched proactively: no channel, nothing to set.
    assert refused.status_code in (403, 422)

    await plan(workspace_id, "starter")
    for _ in range(5):
        assert (await _rule(client, channels=["in_app"])).status_code == 201
    sixth = await _rule(client, channels=["in_app"])
    assert sixth.status_code == 403
    assert sixth.json()["error"]["code"] == "plan_limit"
    read = (await client.get(RULES)).json()
    assert (read["limit"], read["used"], read["upgrade"]) == (5, 5, "growth")
    # Off, it counts no more; another may go on — and that one off may not
    # come back on past the limit.
    first, second = read["rules"][0]["id"], read["rules"][1]["id"]
    off = await client.patch(f"{RULES}/{first}", json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert (await _rule(client, channels=["in_app"])).status_code == 201
    assert (await client.patch(f"{RULES}/{first}", json={"enabled": True})).status_code == 403
    assert (await client.delete(f"{RULES}/{second}")).status_code == 204
    assert (await client.patch(f"{RULES}/{first}", json={"enabled": True})).status_code == 200


async def test_told_once_per_episode_in_leka_and_by_email(
    client: AsyncClient, identity: FakeIdentity, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    made = await _rule(client)
    assert made.status_code == 201, made.text
    rule = made.json()
    await incident(workspace_id, "open")
    await watch(workspace_id, datetime.now(UTC))
    [mail] = _rule_mails(outbox)
    assert mail.to == "nora@acme.example"
    assert "payment-api" in mail.body and "dégradé" in mail.body and "haute" in mail.body
    told = {(d.channel, d.status) for d in await _deliveries(workspace_id)}
    assert told == {("in_app", "sent"), ("email", "sent")}
    # Seen again: never twice.
    await watch(workspace_id, datetime.now(UTC))
    assert len(_rule_mails(outbox)) == 1 and len(await _deliveries(workspace_id)) == 2
    read = (await client.get(RULES)).json()
    channels = {c["key"]: c["status"] for c in read["channels"]}
    # A delivery went: e-mail operational now.
    assert channels["email"] == "operational"
    [kept] = [r for r in read["rules"] if r["id"] == rule["id"]]
    assert {d["channel"] for d in kept["deliveries"]} == {"in_app", "email"}


async def test_after_its_delay_only_again_every_hour_until_taken_in_hand(
    client: AsyncClient, identity: FakeIdentity, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    made = await _rule(client, channels=["email"], confirm_minutes=30, repeat_hours=1)
    assert made.status_code == 201, made.text
    await incident(workspace_id, "open")
    start = datetime.now(UTC)
    await watch(workspace_id, start)
    # Not open long enough: nobody told yet.
    assert _rule_mails(outbox) == []
    await watch(workspace_id, start + timedelta(minutes=31))
    assert len(_rule_mails(outbox)) == 1
    await watch(workspace_id, start + timedelta(minutes=50))
    assert len(_rule_mails(outbox)) == 1
    # An hour on, still open: told again.
    await watch(workspace_id, start + timedelta(minutes=95))
    assert len(_rule_mails(outbox)) == 2
    # Taken in hand: never reminded.
    alert = next(
        a
        for a in (await client.get("/api/v1/monitoring")).json()["open"]
        if a["subject_name"] == "payment-api"
    )
    await client.post(f"/api/v1/monitoring/alerts/{alert['id']}/acknowledge")
    await watch(workspace_id, start + timedelta(hours=4))
    assert len(_rule_mails(outbox)) == 2


async def test_never_told_on_stale_data(
    client: AsyncClient, identity: FakeIdentity, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    assert (await _rule(client, channels=["email"])).status_code == 201
    await incident(workspace_id, "open")
    # The alert opens (the plan's own mail), its rule set after: then what it
    # rests on goes stale before anyone is told by the rule.
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            await monitoring_rules.deliver(session, workspace_id, datetime.now(UTC))
    await watch(workspace_id, datetime.now(UTC))
    _rule_mails(outbox).clear()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            for alert in (await session.scalars(select(MonitoringAlert))).all():
                alert.certainty = "unverified"
            for row in (await session.scalars(select(AlertDelivery))).all():
                await session.delete(row)
            await session.commit()
            outbox.sent.clear()
            assert await monitoring_rules.deliver(session, workspace_id, datetime.now(UTC)) == 0
    assert _rule_mails(outbox) == []


async def test_a_failed_delivery_kept_and_said_a_test_tries_each_channel(
    client: AsyncClient,
    identity: FakeIdentity,
    outbox: Outbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    rule = (await _rule(client)).json()

    tested = await client.post(f"{RULES}/{rule['id']}/test")
    assert tested.status_code == 200, tested.text
    said = {(d["channel"], d["status"], d["alert_id"]) for d in tested.json()["deliveries"]}
    assert said == {("in_app", "sent", None), ("email", "sent", None)}
    [test_mail] = [m for m in outbox.sent if "test" in m.subject]
    assert "« payment-api en panne »" in test_mail.subject

    monkeypatch.setattr(monitoring_rules, "build_email_sender", lambda: Refusing())
    await incident(workspace_id, "open")
    await watch(workspace_id, datetime.now(UTC))
    failed = [d for d in await _deliveries(workspace_id) if d.status == "failed"]
    assert [(d.channel, d.error) for d in failed] == [("email", "ConnectionError: smtp down")]
    channels = {c["key"]: c["status"] for c in (await client.get(RULES)).json()["channels"]}
    assert channels["email"] == "failing"
    assert (await client.post(f"{RULES}/{uuid.uuid4()}/test")).status_code == 404
