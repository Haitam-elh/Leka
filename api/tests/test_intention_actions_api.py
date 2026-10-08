"""Approved decisions carried out, end to end (LEKA-391).

Acme's company model (test_knowledge_graph). Its member asks « Redémarre
Billing API en production »; an admin approves it (LEKA-390), then plans,
starts, follows it. The authorized system is played by an httpx
MockTransport behind the connectors' PublicTransport — the one production
uses — and checks LEKA's signature as a customer's endpoint would.

What these protect:
- Without an authorized system, the step is a person's: they say it is
  done, with what shows it — the intention verifying; a member may not.
- With one, LEKA calls it signed, keeps what it sent and what answered;
  done — verifying. Accepted (202) waits for a person to confirm. Failed —
  the rest not run, the intention failed, retried by a new plan of what
  did not succeed. No answer, or a private address: failed, said why.
- Before anything runs, what must hold is checked and kept: the endpoint
  disabled since, an approver no longer allowed — nothing runs, said why.
- Scheduled: the intention scheduled, run by the sweep at its time;
  cancelled before, approved again; cancelled while running, what had not
  started cancelled, the intention failed.
- Its authorized systems are an admin's, their secret shown once; its
  history is append-only; another workspace's is not there.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from leka.connectors import PublicTransport
from leka.db import session_factory, system_scope
from leka.intentions import actions as actions_module
from leka.intentions.actions import execute_plan, start_due
from leka.intentions.execution import SIGNATURE, verify
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_decisions_api import _asked, _vote, queued, second  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1"
URL = "https://ops.acme.example/leka"


@pytest.fixture(autouse=True)
def jobs(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """No worker here: the plans a route would queue, kept to be run."""
    asked: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID, plan_id: uuid.UUID) -> bool:
        asked.append(plan_id)
        return True

    monkeypatch.setattr(actions_module, "queue_plan", queue)
    from leka.api import actions as actions_api

    monkeypatch.setattr(actions_api, "queue_plan", queue)
    return asked


class System:
    """A customer's endpoint: checks LEKA's signature, answers as told."""

    def __init__(self, secret: str = "", status: int = 200, body: object | None = None) -> None:
        self.secret, self.status, self.body = secret, status, body
        self.received: list[dict[str, Any]] = []
        self.signed: list[bool] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        content = request.content
        self.signed.append(
            verify(
                self.secret,
                request.headers[SIGNATURE],
                content,
                now=int(datetime.now(UTC).timestamp()),
            )
        )
        self.received.append(json.loads(content))
        body = self.body if self.body is not None else {"status": "succeeded", "ref": "run-42"}
        return httpx.Response(self.status, json=body)

    def transport(self, address: str = "93.184.215.14") -> PublicTransport:
        async def resolve(host: str, port: int) -> list[str]:
            return [address]

        return PublicTransport(httpx.MockTransport(self.handler), resolve=resolve)


async def _approved(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, Any]:
    """Asked by the member, approved by the admin — signed in as the admin."""
    _as(identity, acme, "member")
    intention = await _asked(client, acme)
    _as(identity, acme, "admin")
    await _vote(client, intention, "approve")
    return intention


async def _plan(client: AsyncClient, intention: dict[str, Any], code: int = 201) -> Any:
    response = await client.post(f"{API}/intentions/{intention['id']}/plan")
    assert response.status_code == code, response.text
    return response.json()


async def _start(
    client: AsyncClient, intention: dict[str, Any], code: int = 200, **body: Any
) -> Any:
    response = await client.post(f"{API}/intentions/{intention['id']}/plan/start", json=body)
    assert response.status_code == code, response.text
    return response.json()


async def _status(client: AsyncClient, intention: dict[str, Any]) -> str:
    status: str = (await client.get(f"{API}/intentions/{intention['id']}")).json()["status"]
    return status


async def _latest(client: AsyncClient, intention: dict[str, Any]) -> dict[str, Any]:
    plans = (await client.get(f"{API}/intentions/{intention['id']}/plans")).json()
    latest: dict[str, Any] = plans[0]
    return latest


async def _authorize(client: AsyncClient, **body: Any) -> dict[str, Any]:
    payload = {
        "name": "Ops runbooks",
        "url": URL,
        "actions": ["restart"],
        "environments": ["production"],
        **body,
    }
    response = await client.post(f"{API}/action-endpoints", json=payload)
    assert response.status_code == 201, response.text
    made: dict[str, Any] = response.json()
    return made


def _codes(said: dict[str, Any]) -> set[str]:
    return {d["field"] for d in said["error"].get("details") or []}


# ── a person's step ──────────────────────────────────────────────────────────


async def test_without_an_authorized_system_a_person_does_it_and_says_so(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _approved(client, identity, acme)
    plan = await _plan(client, intention)
    [step] = plan["steps"]
    assert (step["action"], step["executor"], step["environment"], step["status"]) == (
        "restart",
        "manual",
        "production",
        "pending",
    )
    # Linked: its history says so.
    detail = (await client.get(f"{API}/intentions/{intention['id']}")).json()
    assert ("action", plan["id"]) in {(lk["kind"], lk["ref_id"]) for lk in detail["links"]}

    started = await _start(client, intention, timezone="Europe/Paris")
    assert started["status"] == "running"
    assert all(check["passed"] for check in started["checks"])
    assert {c["code"] for c in started["checks"]} >= {
        "decision_approved",
        "approvers_allowed",
        "targets_present",
    }
    assert started["steps"][0]["status"] == "awaiting"
    assert await _status(client, intention) == "executing"

    _as(identity, acme, "member")
    url = f"{API}/intentions/{intention['id']}/plan/steps/{step['id']}/report"
    body = {"outcome": "succeeded", "note": "Restarted from the console.", "link": "https://ci/1"}
    assert (await client.post(url, json=body)).status_code == 403

    _as(identity, acme, "admin")
    # A link is http(s): never something a browser would run.
    unsafe = {**body, "link": "javascript:alert(1)"}
    assert (await client.post(url, json=unsafe)).status_code == 422
    done = (await client.post(url, json=body)).json()
    assert done["status"] == "succeeded"
    assert done["steps"][0]["evidence"]["reported"]["note"] == "Restarted from the console."
    assert [e["kind"] for e in done["events"]] == [
        "planned",
        "started",
        "awaiting_person",
        "step_succeeded",
        "succeeded",
        # Its outcome checked next (LEKA-392).
        "verification_started",
    ]
    assert await _status(client, intention) == "verifying"
    history = (await client.get(f"{API}/intentions/{intention['id']}/history")).json()
    assert [h["name"] for h in history[-2:]] == ["execution_started", "executed"]


# ── an authorized system ─────────────────────────────────────────────────────


async def test_an_authorized_system_is_called_signed_its_answer_kept(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    jobs: list[uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    made = await _authorize(client)
    listed = (await client.get(f"{API}/action-endpoints")).json()
    assert [e["name"] for e in listed] == ["Ops runbooks"]
    assert "secret" not in listed[0]
    system = System(secret=made["secret"])

    intention = await _approved(client, identity, acme)
    plan = await _plan(client, intention)
    assert (plan["steps"][0]["executor"], plan["steps"][0]["endpoint_name"]) == (
        "webhook",
        "Ops runbooks",
    )
    started = await _start(client, intention)
    assert started["steps"][0]["status"] == "pending"
    assert jobs == [uuid.UUID(plan["id"])]

    went = await execute_plan(acme["acme"], uuid.UUID(plan["id"]), transport=system.transport())
    assert went == "succeeded"
    assert system.signed == [True]
    [sent] = system.received
    assert (sent["action"], sent["environment"], sent["targets"][0]["name"]) == (
        "restart",
        "production",
        "Billing API",
    )
    latest = await _latest(client, intention)
    evidence = latest["steps"][0]["evidence"]
    assert evidence["request"]["url"] == URL
    assert evidence["request"]["payload"]["delivery"] == latest["steps"][0]["id"]
    assert len(evidence["request"]["sha256"]) == 64
    assert evidence["response"]["status"] == 200
    assert evidence["outcome"] == {
        "status": "succeeded",
        "reason": None,
        "detail": None,
        "ref": "run-42",
        "metrics": {},
    }
    assert await _status(client, intention) == "verifying"


async def test_accepted_waits_for_a_person_to_confirm(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    made = await _authorize(client)
    intention = await _approved(client, identity, acme)
    plan = await _plan(client, intention)
    await _start(client, intention)
    system = System(secret=made["secret"], status=202, body={"status": "accepted", "ref": "job-7"})

    went = await execute_plan(acme["acme"], uuid.UUID(plan["id"]), transport=system.transport())
    assert went == "waiting"
    latest = await _latest(client, intention)
    step = latest["steps"][0]
    # Accepted is not done.
    assert (latest["status"], step["status"]) == ("running", "awaiting")
    assert await _status(client, intention) == "executing"

    url = f"{API}/intentions/{intention['id']}/plan/steps/{step['id']}/report"
    confirmed = await client.post(url, json={"outcome": "succeeded", "note": "job-7 green"})
    assert confirmed.json()["status"] == "succeeded"
    assert await _status(client, intention) == "verifying"


async def test_a_failure_stops_it_says_why_and_is_retried(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    made = await _authorize(client)
    intention = await _approved(client, identity, acme)
    plan = await _plan(client, intention)
    await _start(client, intention)
    failing = System(secret=made["secret"], status=500, body={"detail": "pod crashloop"})

    went = await execute_plan(acme["acme"], uuid.UUID(plan["id"]), transport=failing.transport())
    assert went == "failed"
    latest = await _latest(client, intention)
    assert (latest["status"], latest["error"]) == ("failed", "http_500")
    assert latest["steps"][0]["evidence"]["response"]["excerpt"] == '{"detail":"pod crashloop"}'
    assert await _status(client, intention) == "failed"
    history = (await client.get(f"{API}/intentions/{intention['id']}/history")).json()
    assert (history[-1]["name"], history[-1]["detail"]["error"]) == ("failed", "http_500")

    # Retried: a new plan of what did not succeed, run again.
    retry = await _plan(client, intention)
    assert (retry["number"], [s["action"] for s in retry["steps"]]) == (2, ["restart"])
    await _start(client, intention)
    assert await _status(client, intention) == "executing"
    ok = System(secret=made["secret"])
    assert await execute_plan(acme["acme"], uuid.UUID(retry["id"]), transport=ok.transport()) == (
        "succeeded"
    )
    assert await _status(client, intention) == "verifying"


@pytest.mark.parametrize(
    ("transport", "reason"),
    [("timeout", "no_answer"), ("private", "blocked_address")],
)
async def test_no_answer_or_a_private_address_is_a_failure(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    transport: str,
    reason: str,
) -> None:
    _as(identity, acme, "admin")
    await _authorize(client)
    intention = await _approved(client, identity, acme)
    plan = await _plan(client, intention)
    await _start(client, intention)

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    used = (
        PublicTransport(httpx.MockTransport(slow), resolve=public)
        if transport == "timeout"
        else System().transport(address="10.0.0.5")
    )
    assert await execute_plan(acme["acme"], uuid.UUID(plan["id"]), transport=used) == "failed"
    latest = await _latest(client, intention)
    assert latest["steps"][0]["error"] == reason


# ── checked before it runs ───────────────────────────────────────────────────


async def test_what_must_hold_is_checked_nothing_runs_otherwise(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    second: uuid.UUID,
) -> None:
    _as(identity, acme, "admin")
    made = await _authorize(client)
    intention = await _approved(client, identity, acme)
    await _plan(client, intention)

    # Disabled since it was planned: refused, said why, kept with the plan.
    off = await client.patch(
        f"{API}/action-endpoints/{made['endpoint']['id']}", json={"enabled": False}
    )
    assert off.status_code == 200, off.text
    refused = await _start(client, intention, code=409)
    assert "check.endpoint_allows" in _codes(refused)
    latest = await _latest(client, intention)
    assert latest["status"] == "planned"
    assert {c["code"] for c in latest["checks"] if not c["passed"]} == {"endpoint_allows"}
    assert await _status(client, intention) == "approved"

    # Its approver no longer allowed to approve: refused.
    await client.patch(f"{API}/action-endpoints/{made['endpoint']['id']}", json={"enabled": True})
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE memberships SET role = 'member'"
                    " WHERE user_id = :u AND workspace_id = :w"
                ),
                {"u": acme["admin"], "w": acme["acme"]},
            )
            await session.commit()
    _as(identity, acme, "second")
    demoted = await _start(client, intention, code=409)
    assert "check.approvers_allowed" in _codes(demoted)


# ── scheduled, cancelled ─────────────────────────────────────────────────────


async def test_scheduled_then_run_by_the_sweep_at_its_time(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _approved(client, identity, acme)
    await _plan(client, intention)
    later = datetime.now(UTC) + timedelta(hours=2)
    scheduled = await _start(client, intention, scheduled_for=later.isoformat())
    assert scheduled["status"] == "scheduled"
    assert await _status(client, intention) == "scheduled"

    assert await start_due(now=datetime.now(UTC)) == {"started": 0, "blocked": 0}
    counts = await start_due(now=later + timedelta(minutes=1))
    assert counts == {"started": 1, "blocked": 0}
    latest = await _latest(client, intention)
    assert (latest["status"], latest["steps"][0]["status"]) == ("running", "awaiting")
    assert await _status(client, intention) == "executing"


async def test_cancelled_before_it_runs_it_is_approved_again(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _approved(client, identity, acme)
    await _plan(client, intention)
    await _start(
        client, intention, scheduled_for=(datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    url = f"{API}/intentions/{intention['id']}/plan/cancel"
    assert (await client.post(url, json={})).status_code == 422
    cancelled = (await client.post(url, json={"reason": "The incident cleared."})).json()
    assert (cancelled["status"], cancelled["steps"][0]["status"]) == ("cancelled", "cancelled")
    assert await _status(client, intention) == "approved"
    # Approved again: planned anew.
    assert (await _plan(client, intention))["number"] == 2


async def test_cancelled_while_running_what_had_not_started_is_cancelled(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _approved(client, identity, acme)
    await _plan(client, intention)
    await _start(client, intention)
    stopped = (
        await client.post(
            f"{API}/intentions/{intention['id']}/plan/cancel", json={"reason": "Wrong service."}
        )
    ).json()
    assert (stopped["status"], stopped["error"]) == ("cancelled", "cancelled")
    assert stopped["steps"][0]["status"] == "cancelled"
    assert [e["kind"] for e in stopped["events"]][-2:] == ["cancel_requested", "cancelled"]
    assert await _status(client, intention) == "failed"
    nothing = await client.post(
        f"{API}/intentions/{intention['id']}/plan/cancel", json={"reason": "Again."}
    )
    assert nothing.status_code == 409


# ── who may, audit ───────────────────────────────────────────────────────────


async def test_an_admins_systems_a_history_never_changed_another_workspace(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "member")
    refused = await client.post(
        f"{API}/action-endpoints",
        json={"name": "x", "url": URL, "actions": ["restart"], "environments": ["*"]},
    )
    assert refused.status_code == 403
    _as(identity, acme, "admin")
    private = await client.post(
        f"{API}/action-endpoints",
        json={
            "name": "x",
            "url": "http://10.0.0.5/run",
            "actions": ["restart"],
            "environments": ["*"],
        },
    )
    assert private.status_code == 422

    intention = await _approved(client, identity, acme)
    _as(identity, acme, "member")
    assert (await client.post(f"{API}/intentions/{intention['id']}/plan")).status_code == 403
    _as(identity, acme, "admin")
    plan = await _plan(client, intention)
    event = plan["events"][0]["id"]
    with system_scope():
        async with session_factory() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    text("UPDATE intention_plan_events SET kind = 'x' WHERE id = :e"), {"e": event}
                )

    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/intentions/{intention['id']}/plans")).status_code == 404
    assert (await client.get(f"{API}/action-endpoints")).json() == []
    assert (await client.post(f"{API}/intentions/{intention['id']}/plan")).status_code == 404
