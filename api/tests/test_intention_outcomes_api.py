"""What came of approved actions, and each intention's whole story, end to
end (LEKA-392).

Acme's company model (test_knowledge_graph). Its member asks « Redémarre
Billing API en production »; an admin approves it (LEKA-390), plans it,
runs it (LEKA-391) — by an authorized system, played by an httpx
MockTransport behind PublicTransport, or by a person who says it is done.
An incident on Billing API comes the way it does in production: a PagerDuty
record, normalised, stored, the model built again.

What these protect:
- Before it runs, a plan expects LEKA's defaults — Billing API healthy
  after a restart, its open incidents resolved; who may approve changes
  them; once it started, or one that cannot be checked, refused; a member
  may not.
- Once it ran, its outcome is verified: read from the model — the incidents
  open on it — and from what the system reported; met, the intention
  completed, the model built again (an operation whose reason names it),
  the outcome linked; nothing met that was not observed.
- A person's word on an expectation, with a link that is http(s); at the
  deadline, or concluded by a person, what is not met is said — partial,
  or failed — and the intention failed, said why.
- With nothing expected, what ran is the outcome once it settled.
- Its timeline holds its analysis, decision, votes, plan, steps and
  outcome, each by who and when, filtered; the workspace's history too;
  another workspace sees none of it.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.api import outcomes as outcomes_api
from leka.connectors import Capability, SourceKind
from leka.db import session_factory, system_scope, workspace_scope
from leka.intentions import verification as verification_module
from leka.intentions.actions import execute_plan
from leka.intentions.outcome import SETTLE
from leka.intentions.verification import verify_due
from tests.conftest import FakeIdentity
from tests.test_application_landscape import _record, _store
from tests.test_context_engine import _sql, model
from tests.test_intention_actions_api import (  # noqa: F401 — jobs is a fixture
    System,
    _approved,
    _authorize,
    _latest,
    _plan,
    _start,
    _status,
    jobs,
)
from tests.test_intention_decisions_api import queued  # noqa: F401
from tests.test_knowledge_graph import BILLING
from tests.test_pagerduty_connector import incident as pagerduty_incident
from tests.test_relationships_engine import _build
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1"


@pytest.fixture(autouse=True)
def builds(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """No worker here: the model builds a success asks for, kept."""
    asked: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID) -> bool:
        asked.append(workspace_id)
        return True

    monkeypatch.setattr(outcomes_api, "queue_model_build", queue)
    monkeypatch.setattr(verification_module, "queue_model_build", queue)
    return asked


def _url(intention: dict[str, Any], path: str = "") -> str:
    return f"{API}/intentions/{intention['id']}{path}"


async def _expect(
    client: AsyncClient, intention: dict[str, Any], items: list[dict[str, Any]], code: int = 200
) -> Any:
    response = await client.put(_url(intention, "/plan/expectations"), json={"expectations": items})
    assert response.status_code == code, response.text
    return response.json()


async def _verification(client: AsyncClient, intention: dict[str, Any]) -> dict[str, Any]:
    found = (await client.get(_url(intention, "/verifications"))).json()
    latest: dict[str, Any] = found[0]
    return latest


async def _post(client: AsyncClient, path: str, code: int = 200, **body: Any) -> Any:
    response = await client.post(path, json=body)
    assert response.status_code == code, response.text
    return response.json()


async def _done_by_hand(client: AsyncClient, intention: dict[str, Any]) -> dict[str, Any]:
    """Started, its one step done by a person: verifying."""
    await _start(client, intention)
    [step] = (await _latest(client, intention))["steps"]
    await _post(
        client,
        _url(intention, f"/plan/steps/{step['id']}/report"),
        outcome="succeeded",
        note="Restarted from the console.",
    )
    assert await _status(client, intention) == "verifying"
    return await _verification(client, intention)


def _seen(verification: dict[str, Any]) -> dict[str, str]:
    return {r["expectation_id"]: r["seen"] for r in verification["results"]}


async def _incident(acme: dict[str, uuid.UUID], number: int, status: str) -> None:
    """An incident on Billing API, as PagerDuty says it: stored, the model
    built again."""
    workspace = acme["acme"]
    with system_scope():
        async with session_factory() as session:
            pagerduty = await session.scalar(
                text("SELECT id FROM sources WHERE workspace_id = :w AND kind = 'pagerduty'"),
                {"w": workspace},
            )
    payload = {
        **pagerduty_incident(number, "PBILL01"),
        "title": f"Billing API errors {number}",
        "status": status,
        "service": {"id": "PBILL01", "summary": "Billing API"},
    }
    await _store(workspace, pagerduty, _record(SourceKind.PAGERDUTY, Capability.INCIDENTS, payload))
    await _build(workspace)
    # Shown today, as the model fixture has it: built again, the model takes
    # the fixtures' dates back, and what a source last showed a month ago is
    # stale evidence, one more approval (2026-10-27, a month after them).
    await _sql(workspace, "UPDATE entities SET last_seen_at = now()")


async def _synced(acme: dict[str, uuid.UUID], *ids: str, closed: bool = False) -> None:
    """Their next sync: shown now — an incident resolved, when closed — as
    the model holds them then."""
    state = '{"state": "closed"}' if closed else "{}"
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE entities SET last_seen_at = now(), attributes = attributes || "
                    "CASE WHEN type = 'incident' THEN CAST(:state AS jsonb) "
                    "ELSE '{}'::jsonb END WHERE id = ANY(:ids)"
                ),
                {"ids": [uuid.UUID(i) for i in ids], "state": state},
            )
            await session.commit()


async def _operation(acme: dict[str, uuid.UUID], operation_id: str) -> tuple[str, str]:
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT kind, reason FROM model_operations WHERE id = :o"),
                    {"o": uuid.UUID(operation_id)},
                )
            ).one()
    return str(row.kind), str(row.reason)


# ── what a system reported ───────────────────────────────────────────────────


async def test_what_a_system_reported_is_checked_the_context_built_again(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    jobs: list[uuid.UUID],
    builds: list[uuid.UUID],
) -> None:
    intention = await _approved(client, identity, acme)
    authorized = await _authorize(client)
    system = System(
        authorized["secret"],
        body={"status": "succeeded", "ref": "run-7", "metrics": {"p95_ms": 180}},
    )
    plan = await _plan(client, intention)
    billing = str(model[BILLING])
    # LEKA's default: what was restarted, healthy.
    assert [(e["id"], e["kind"], e["target"]["id"]) for e in plan["expectations"]] == [
        (f"healthy:{billing}", "healthy", billing)
    ]
    # Its latency, as the system that acted reports it, instead.
    p95 = {
        "id": "p95",
        "kind": "metric",
        "name": "p95_ms",
        "comparator": "lte",
        "value": 300,
        "source": "system",
    }
    [kept] = await _expect(client, intention, [p95])
    assert (kept["id"], kept["comparator"], kept["value"]) == ("p95", "lte", 300)
    assert (await _latest(client, intention))["expectations"] == [kept]

    await _start(client, intention)
    went = await execute_plan(acme["acme"], uuid.UUID(plan["id"]), transport=system.transport())
    assert went == "succeeded"
    assert system.received[0]["action"] == "restart"
    assert await _status(client, intention) == "verifying"

    verification = await _verification(client, intention)
    assert (verification["status"], verification["plan_id"]) == ("verifying", plan["id"])
    deadline = datetime.fromisoformat(verification["deadline"])
    after = datetime.fromisoformat(verification["observe_after"])
    assert deadline - after == timedelta(hours=24) - SETTLE

    # Read now, without waiting for the sweep: met.
    done = await _post(client, _url(intention, "/verification/check"))
    assert done["status"] == "succeeded"
    assert done["results"] == [
        {"expectation_id": "p95", "seen": "met", "value": 180, "detail": None, "reported": None}
    ]
    assert await _status(client, intention) == "completed"
    # The company's context told: the model built again, the operation
    # saying whose outcome asked for it.
    update = done["context_update"]
    assert update["kind"] == "rebuild"
    kind, reason = await _operation(acme, update["operation_id"])
    assert kind == "rebuild"
    assert intention["title"] in reason and "LEKA-392" in reason
    assert builds == [acme["acme"]]
    detail = (await client.get(_url(intention))).json()
    assert ("outcome", done["id"], "succeeded") in {
        (lk["kind"], lk["ref_id"], lk["label"]) for lk in detail["links"]
    }
    history = (await client.get(_url(intention, "/history"))).json()
    assert history[-1]["name"] == "verified"
    assert history[-1]["detail"]["outcome"] == "succeeded"
    # Once concluded, nothing more to check.
    assert (await client.post(_url(intention, "/verification/check"))).status_code == 409


# ── what the model says ──────────────────────────────────────────────────────


async def test_healthy_is_read_from_the_incidents_open_on_it(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    await _incident(acme, 7, "triggered")
    intention = await _approved(client, identity, acme)
    plan = await _plan(client, intention)
    billing = str(model[BILLING])
    healthy, incidents = plan["expectations"]
    assert (healthy["id"], incidents["id"]) == (f"healthy:{billing}", f"incidents:{billing}")
    [incident_id] = incidents["incidents"]

    verification = await _done_by_hand(client, intention)
    assert verification["status"] == "verifying"
    # The incident still open on it: neither is met — not concluded before
    # its deadline.
    still = await _post(client, _url(intention, "/verification/check"))
    assert still["status"] == "verifying"
    assert _seen(still) == {healthy["id"]: "not_met", incidents["id"]: "not_met"}
    assert await _status(client, intention) == "verifying"

    # Synced: the incident resolved, Billing API shown active since — both met.
    await _synced(acme, incident_id, billing, closed=True)
    done = await _post(client, _url(intention, "/verification/check"))
    assert done["status"] == "succeeded", done["results"]
    assert _seen(done) == {healthy["id"]: "met", incidents["id"]: "met"}
    assert await _status(client, intention) == "completed"


async def test_at_its_deadline_what_is_not_met_is_said(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
) -> None:
    await _incident(acme, 8, "acknowledged")
    intention = await _approved(client, identity, acme)
    plan = await _plan(client, intention)
    confirmed = {"id": "checkout", "kind": "confirmed", "said": "Checkout works end to end"}
    await _expect(client, intention, [*plan["expectations"], confirmed])
    verification = await _done_by_hand(client, intention)
    assert _seen(verification) == {}

    # Before it settled, the sweep leaves it.
    started = datetime.fromisoformat(verification["created_at"])
    assert (await verify_due(now=started + timedelta(minutes=1)))["observed"] == 0

    said = await _post(
        client,
        _url(intention, "/verification/expectations/checkout/report"),
        met=True,
        note="Paid an order on the shop.",
        link="https://acme.example/orders/42",
    )
    assert said["status"] == "verifying"
    [checkout] = [r for r in said["results"] if r["expectation_id"] == "checkout"]
    assert checkout["seen"] == "met"
    assert checkout["reported"]["by"] == str(acme["admin"])
    assert checkout["reported"]["link"] == "https://acme.example/orders/42"

    # Settled: read again, the incident still open — still verifying.
    counts = await verify_due(now=started + SETTLE + timedelta(minutes=1))
    assert counts == {"observed": 1, "concluded": 0}
    # Its deadline: concluded with what was observed — a part only.
    deadline = datetime.fromisoformat(verification["deadline"])
    counts = await verify_due(now=deadline + timedelta(minutes=1))
    assert counts == {"observed": 1, "concluded": 1}
    concluded = await _verification(client, intention)
    assert concluded["status"] == "partial"
    assert concluded["concluded_by"] is None
    # A person's word, kept as it was said.
    assert _seen(concluded)["checkout"] == "met"
    assert await _status(client, intention) == "failed"
    history = (await client.get(_url(intention, "/history"))).json()
    assert history[-1]["reason"] == "Only part of what was expected came."
    # Not a success: the model is not asked to be built again.
    assert builds == []
    links = (await client.get(_url(intention))).json()["links"]
    assert ("outcome", "partial") in {(lk["kind"], lk["label"]) for lk in links}


async def test_a_persons_word_and_a_person_concluding(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _approved(client, identity, acme)
    await _plan(client, intention)
    confirmed = {"id": "checkout", "kind": "confirmed", "said": "Checkout works end to end"}
    await _expect(client, intention, [confirmed])
    await _done_by_hand(client, intention)
    report = _url(intention, "/verification/expectations/checkout/report")
    body: dict[str, Any] = {
        "met": False,
        "note": "Payments still time out.",
        "link": "https://ci/9",
    }

    _as(identity, acme, "member")
    assert (await client.post(report, json=body)).status_code == 403
    assert (await client.get(_url(intention, "/verifications"))).status_code == 200
    _as(identity, acme, "admin")
    # A link is http(s): never something a browser would run.
    unsafe = {**body, "link": "javascript:alert(1)"}
    assert (await client.post(report, json=unsafe)).status_code == 422
    missing = _url(intention, "/verification/expectations/nothing/report")
    assert (await client.post(missing, json=body)).status_code == 404

    # Not met, said: still verifying until its deadline — or a person.
    said = await _post(client, report, **body)
    assert (said["status"], _seen(said)) == ("verifying", {"checkout": "not_met"})
    concluded = await _post(
        client, _url(intention, "/verification/conclude"), note="Rolled back by hand instead."
    )
    assert (concluded["status"], concluded["concluded_by"]) == ("failed", str(acme["admin"]))
    assert concluded["detail"]["note"] == "Rolled back by hand instead."
    assert await _status(client, intention) == "failed"
    history = (await client.get(_url(intention, "/history"))).json()
    assert (history[-1]["actor"], history[-1]["reason"]) == (
        "person",
        "Rolled back by hand instead.",
    )
    again = await client.post(_url(intention, "/verification/conclude"), json={"note": "Again."})
    assert again.status_code == 409
    # Everything ran, what was expected did not come: tried again, all of it.
    retried = await _plan(client, intention)
    assert (retried["number"], [s["action"] for s in retried["steps"]]) == (2, ["restart"])
    assert retried["expectations"][0]["kind"] == "healthy"


async def test_expectations_are_set_before_it_runs_by_who_may_approve(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
) -> None:
    intention = await _approved(client, identity, acme)
    healthy = {"id": "h", "kind": "healthy", "target": {"id": str(model[BILLING])}}
    # No plan yet.
    refused = await _expect(client, intention, [healthy], code=409)
    assert refused["error"]["details"][0]["message"] == "not_planned"
    await _plan(client, intention)

    _as(identity, acme, "member")
    await _expect(client, intention, [healthy], code=403)
    _as(identity, acme, "admin")
    for wrong in (
        [{"id": "x", "kind": "vibes"}],
        [{"id": "x", "kind": "healthy", "target": {"id": "billing"}}],
        [{"id": "x", "kind": "metric", "name": "p95", "comparator": "about", "value": 1}],
        [healthy, healthy],
    ):
        said = await _expect(client, intention, wrong, code=422)
        assert said["error"]["code"] == "validation_failed"

    # Nothing expected: what ran is the outcome, once it settled.
    assert await _expect(client, intention, []) == []
    events = [e["kind"] for e in (await _latest(client, intention))["events"]]
    assert events[-1] == "expectations_set"
    verification = await _done_by_hand(client, intention)
    await _expect(client, intention, [healthy], code=409)
    started = datetime.fromisoformat(verification["created_at"])
    assert (await verify_due(now=started + SETTLE))["concluded"] == 1
    assert (await _verification(client, intention))["status"] == "succeeded"
    assert await _status(client, intention) == "completed"
    assert builds == [acme["acme"]]


# ── its whole story ──────────────────────────────────────────────────────────


async def test_its_whole_story_in_one_timeline_filtered(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _approved(client, identity, acme)
    await _plan(client, intention)
    await _expect(client, intention, [{"id": "ok", "kind": "confirmed", "said": "It works"}])
    await _done_by_hand(client, intention)
    await _post(
        client, _url(intention, "/verification/expectations/ok/report"), met=True, note="It works."
    )
    assert await _status(client, intention) == "completed"

    story = (await client.get(_url(intention, "/timeline"))).json()
    ats = [item["at"] for item in story]
    assert ats == sorted(ats, reverse=True)
    assert {item["category"] for item in story} == {
        "intention",
        "analysis",
        "decision",
        "action",
        "outcome",
    }
    kinds = {(item["category"], item["kind"]) for item in story}
    assert {
        ("intention", "created"),
        ("analysis", "analysis_started"),
        ("analysis", "analysis_complete"),
        ("decision", "decision_opened"),
        ("decision", "vote_approve"),
        ("action", "planned"),
        ("action", "step_succeeded"),
        ("outcome", "expectations_set"),
        ("outcome", "verification_started"),
        ("outcome", "expectation_reported"),
        ("outcome", "verification_succeeded"),
        ("intention", "verified"),
    } <= kinds
    # At the same instant, the cause before what it moved.
    told = [(item["category"], item["kind"]) for item in reversed(story)]
    for cause, effect in (
        (("decision", "vote_approve"), ("intention", "approved")),
        (("action", "succeeded"), ("outcome", "verification_started")),
        (("outcome", "verification_succeeded"), ("intention", "verified")),
    ):
        assert told.index(cause) < told.index(effect)
    vote = next(item for item in story if item["kind"] == "vote_approve")
    assert (vote["actor"], vote["by"]) == ("person", str(acme["admin"]))
    assert vote["by_name"]

    # Filtered: by kind, by who, by when.
    outcome = (
        await client.get(_url(intention, "/timeline"), params={"category": "outcome"})
    ).json()
    assert {item["category"] for item in outcome} == {"outcome"}
    both = await client.get(
        _url(intention, "/timeline"), params=[("category", "decision"), ("category", "outcome")]
    )
    assert {item["category"] for item in both.json()} == {"decision", "outcome"}
    people = (await client.get(_url(intention, "/timeline"), params={"actor": "person"})).json()
    assert people and {item["actor"] for item in people} == {"person"}
    later = (
        await client.get(_url(intention, "/timeline"), params={"since": story[2]["at"]})
    ).json()
    assert later == [item for item in story if item["at"] >= story[2]["at"]]
    earlier = (
        await client.get(_url(intention, "/timeline"), params={"until": story[2]["at"]})
    ).json()
    assert earlier == [item for item in story if item["at"] < story[2]["at"]]
    assert (await client.get(_url(intention, "/timeline"), params={"limit": 2})).json() == story[:2]
    assert (
        await client.get(_url(intention, "/timeline"), params={"category": "vibes"})
    ).status_code == 422

    # The workspace's: every intention's, each with its title; by who.
    workspace = (await client.get(f"{API}/intention-history")).json()
    assert {item["id"] for item in story} <= {item["id"] for item in workspace}
    assert {item["title"] for item in workspace} == {intention["title"]}
    member = (
        await client.get(f"{API}/intention-history", params={"by": str(acme["member"])})
    ).json()
    assert member and {item["by"] for item in member} == {str(acme["member"])}
    assert ("intention", "created") in {(item["category"], item["kind"]) for item in member}

    # Read by members; another workspace sees none of it.
    _as(identity, acme, "member")
    assert (await client.get(_url(intention, "/timeline"))).status_code == 200
    _as(identity, acme, "other_admin")
    assert (await client.get(_url(intention, "/timeline"))).status_code == 404
    assert (await client.get(_url(intention, "/verifications"))).status_code == 404
    assert (await client.get(f"{API}/intention-history")).json() == []
    assert (await client.post(_url(intention, "/verification/check"))).status_code == 404
