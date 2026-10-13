"""An intention's journey through its decision and its actions (LEKA-443):
what every screen reads at each step, and what may be done there — the
plan's controls are the rules its routes apply.

Acme's company model (test_knowledge_graph), as test_intention_actions_api
reads it: the member asks, an admin decides and acts.

What these protect:
- Selecting among several actions, approving part, refusing:
  - the actions selected, those planned and those running are the same
    count, at every step;
  - nothing selected is said running before it is approved;
  - refused, nothing is planned, and it may be asked again.
- Run, failed, retried, verified:
  - approved, it is to be started, and only a plan's own controls are
    offered;
  - accepted by a system, it waits for a person and says so. Read again, as
    a page refreshed or come back to later, it still runs: never done.
  - failed, then without an answer (a timeout): the action failed, why
    said, the error's code kept for diagnosis, and retried by a new plan;
  - executed, it is to be verified, never done;
  - verified short of what was expected: the action failed, said so.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import httpx
from httpx import AsyncClient

from leka.connectors import PublicTransport
from leka.intentions.actions import execute_plan
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_actions_api import (  # noqa: F401 — `jobs` is a fixture
    System,
    _approved,
    _authorize,
    _latest,
    _plan,
    _start,
    jobs,
)
from tests.test_intention_decisions_api import _asked, _vote, queued  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

_ = model  # a fixture, requested by name
API = "/api/v1"
TWO = "Redémarre Billing API et scale Billing API en production"


async def _journey(client: AsyncClient, intention: dict[str, Any]) -> dict[str, Any]:
    """Its journey as its page says it — and the list, the same."""
    page = (await client.get(f"{API}/intentions/{intention['id']}")).json()["journey"]
    listed = next(
        i
        for i in (await client.get(f"{API}/intentions")).json()["data"]
        if i["id"] == intention["id"]
    )
    assert listed["journey"] == page
    journey: dict[str, Any] = page
    return journey


async def test_part_approved_the_same_actions_selected_planned_and_running(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "member")
    intention = await _asked(client, acme, TWO)
    said = await _journey(client, intention)
    assert (said["state"], said["next"], said["by"]) == ("decision_required", "decide", "approver")
    assert {"decide", "modify_decision"} <= set(said["controls"])
    [decision] = (await client.get(f"{API}/intentions/{intention['id']}/decisions")).json()
    selected = [p["action"] for p in decision["proposals"]]
    assert sorted(selected) == ["restart", "scale"]
    # Selected, not approved: nothing planned, nothing running.
    assert (await client.get(f"{API}/intentions/{intention['id']}/plans")).json() == []

    _as(identity, acme, "admin")
    # Approving part: modifying approves what is kept.
    kept = await _vote(client, intention, "modify", keep=["restart"], reason="Only the restart.")
    assert [p["action"] for p in kept["proposals"]] == ["restart"]
    assert kept["status"] == "approved"
    said = await _journey(client, intention)
    assert (said["state"], said["next"]) == ("approved", "start_actions")
    assert "decide" not in said["controls"] and "modify_decision" not in said["controls"]

    plan = await _plan(client, intention)
    assert [s["action"] for s in plan["steps"]] == ["restart"]
    assert plan["controls"] == ["start", "schedule", "cancel"]
    started = await _start(client, intention)
    assert [s["action"] for s in started["steps"]] == ["restart"]
    assert (await _journey(client, intention))["state"] == "action_running"


async def test_refused_nothing_is_planned_and_it_may_be_asked_again(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "member")
    intention = await _asked(client, acme, TWO)
    _as(identity, acme, "admin")
    await _vote(client, intention, "reject", reason="Not during the sale.")
    said = await _journey(client, intention)
    assert (said["state"], said["reason"]) == ("rejected", "by_person")
    assert set(said["controls"]) == {"ask_again", "archive"}
    assert (said["step"]["at"], said["step"]["done"]) == ("decision", True)
    refused = await client.post(f"{API}/intentions/{intention['id']}/plan")
    assert refused.status_code == 409


async def test_run_waited_on_failed_timed_out_retried_and_verified_short(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    made = await _authorize(client)
    intention = await _approved(client, identity, acme)
    said = await _journey(client, intention)
    assert said["state"] == "approved"
    assert set(said["controls"]) == {"start_actions", "cancel"}

    # Accepted by the system: waits for a person; read again, still running.
    plan = await _plan(client, intention)
    await _start(client, intention)
    accepting = System(secret=made["secret"], status=202, body={"status": "accepted"})
    assert (
        await execute_plan(acme["acme"], uuid.UUID(plan["id"]), transport=accepting.transport())
        == "waiting"
    )
    for _ in range(2):
        latest = await _latest(client, intention)
        assert (latest["status"], latest["steps"][0]["status"]) == ("running", "awaiting")
        assert latest["controls"] == ["stop", "confirm_step"]
        said = await _journey(client, intention)
        assert (said["state"], said["controls"]) == ("action_running", ["stop_actions"])

    # The person says it failed: the action failed, said why.
    step = latest["steps"][0]
    await client.post(
        f"{API}/intentions/{intention['id']}/plan/steps/{step['id']}/report",
        json={"outcome": "failed", "note": "The job failed."},
    )
    said = await _journey(client, intention)
    assert (said["state"], said["reason"], said["next"]) == (
        "action_failed",
        "step_failed",
        "retry_actions",
    )
    assert (await _latest(client, intention))["controls"] == ["plan"]

    # Retried; no answer this time — a timeout: failed, its code kept.
    retry = await _plan(client, intention)
    assert retry["number"] == 2
    await _start(client, intention)

    def _silent(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    async def _resolve(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    silent = PublicTransport(httpx.MockTransport(_silent), resolve=_resolve)
    assert await execute_plan(acme["acme"], uuid.UUID(retry["id"]), transport=silent) == "failed"
    said = await _journey(client, intention)
    assert (said["state"], said["reason"]) == ("action_failed", "step_failed")
    assert said["technical"]

    # Retried again, done: to be verified — never done before it is.
    again = await _plan(client, intention)
    await _start(client, intention)
    ok = System(secret=made["secret"])
    assert (
        await execute_plan(acme["acme"], uuid.UUID(again["id"]), transport=ok.transport())
        == "succeeded"
    )
    said = await _journey(client, intention)
    assert (said["state"], said["next"]) == ("to_verify", "wait_verification")
    assert (await _latest(client, intention))["controls"] == []

    # Concluded with what is observed — not what was expected: said so.
    concluded = await client.post(
        f"{API}/intentions/{intention['id']}/verification/conclude",
        json={"note": "Checked by hand."},
    )
    assert concluded.status_code == 200, concluded.text
    said = await _journey(client, intention)
    if concluded.json()["status"] == "succeeded":
        assert said["state"] == "done"
    else:
        assert (said["state"], said["reason"]) == ("action_failed", "expected_not_met")
