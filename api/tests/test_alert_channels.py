"""The channels connected by a webhook (LEKA-496) — Slack, Microsoft Teams,
Discord — on the demo company, its incident OPS-1841 on payment-api; the
webhooks a fake server.

What these protect: connected only by who manages the sources, only to its
tool's own https webhook — anything else refused; its URL kept encrypted,
shown by its hint only, never read back; untested until a message went,
then operational or failing, its error said; tried at most three times on
a 5xx, once on a refusal; an alert told once to it, never twice; in the
plans that include e-mail only; SMS and WhatsApp still « unavailable ».
"""

# ruff: noqa: F811 — the outbox fixture imported to be requested by name.

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.db import session_factory, workspace_scope
from leka.monitoring import ChannelEndpoint, watch
from leka.monitoring import webhooks as webhooks_module
from tests.conftest import FakeIdentity
from tests.test_alert_rules import RULES, _deliveries, _rule, outbox  # noqa: F401
from tests.test_monitoring_api import Outbox, demo, incident, plan

pytestmark = pytest.mark.integration

CHANNELS = "/api/v1/monitoring/channels"
SLACK = "https://hooks.slack.com/services/T000/B000/abcdefghijkl"


class Hook:
    """A webhook server: what it was sent, the status it answers."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append((request.url.host, json.loads(request.content)))
        return httpx.Response(self.status)


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Hook:
    server = Hook()
    monkeypatch.setattr(webhooks_module, "_transport", lambda: httpx.MockTransport(server.handler))

    async def no_pause(attempt: int) -> None:
        return None

    monkeypatch.setattr(webhooks_module, "_pause", no_pause)
    return server


async def _channel(client: AsyncClient, key: str) -> dict:  # type: ignore[type-arg]
    read = (await client.get(RULES)).json()
    return next(c for c in read["channels"] if c["key"] == key)


async def test_connected_only_to_its_tools_webhook_kept_encrypted_shown_by_its_hint(
    client: AsyncClient, identity: FakeIdentity, hook: Hook
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    assert (await _channel(client, "slack"))["status"] == "not_connected"

    for wrong in (
        "http://hooks.slack.com/services/T/B/x",
        "https://evil.example/services/T/B/x",
        "https://hooks.slack.com/",
        "https://discord.com/api/webhooks/1/x",
    ):
        refused = await client.put(f"{CHANNELS}/slack", json={"url": wrong})
        assert refused.status_code == 422, wrong
    assert (await client.put(f"{CHANNELS}/sms", json={"url": SLACK})).status_code == 422

    made = await client.put(f"{CHANNELS}/slack", json={"url": SLACK})
    assert made.status_code == 200, made.text
    said = made.json()
    assert said["status"] == "untested" and said["hint"] == "hooks.slack.com/…ijkl"
    assert SLACK not in made.text
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            row = await session.scalar(select(ChannelEndpoint))
            assert row is not None and SLACK.encode() not in row.webhook

    # SMS and WhatsApp: never offered.
    assert (await _channel(client, "sms"))["status"] == "unavailable"
    assert (await _channel(client, "whatsapp"))["status"] == "unavailable"

    assert (await client.delete(f"{CHANNELS}/slack")).status_code == 204
    assert (await _channel(client, "slack"))["status"] == "not_connected"


async def test_tested_operational_or_failing_tried_three_times_on_a_5xx_once_on_a_refusal(
    client: AsyncClient, identity: FakeIdentity, hook: Hook
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    await client.put(f"{CHANNELS}/slack", json={"url": SLACK})

    tested = (await client.post(f"{CHANNELS}/slack/test")).json()
    assert tested["status"] == "operational" and tested["error"] is None
    assert len(hook.sent) == 1 and "text" in hook.sent[0][1]  # type: ignore[operator]

    hook.status = 503
    tested = (await client.post(f"{CHANNELS}/slack/test")).json()
    assert (tested["status"], tested["error"]) == ("failing", "HTTP 503")
    assert len(hook.sent) == 1 + webhooks_module.ATTEMPTS

    hook.status = 404
    before = len(hook.sent)
    tested = (await client.post(f"{CHANNELS}/slack/test")).json()
    assert tested["error"] == "HTTP 404" and len(hook.sent) == before + 1


async def test_an_alert_told_once_to_its_webhook(
    client: AsyncClient, identity: FakeIdentity, hook: Hook, outbox: Outbox
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "growth")
    await client.put(f"{CHANNELS}/discord", json={"url": "https://discord.com/api/webhooks/1/abc"})
    made = await _rule(client, channels=["in_app", "discord"], recipients=[])
    assert made.status_code == 201, made.text

    await incident(workspace_id, "open")
    await watch(workspace_id, datetime.now(UTC))
    await watch(workspace_id, datetime.now(UTC))
    [(host, body)] = hook.sent
    assert host == "discord.com" and "payment-api" in body["content"]  # type: ignore[index]
    told = {(d.channel, d.status) for d in await _deliveries(workspace_id)}
    assert told == {("in_app", "sent"), ("discord", "sent")}


async def test_in_the_plans_that_include_email_only(
    client: AsyncClient, identity: FakeIdentity, hook: Hook
) -> None:
    workspace_id = await demo(identity)
    await plan(workspace_id, "starter")
    assert (await _channel(client, "slack"))["status"] == "not_in_plan"
    _ = uuid
