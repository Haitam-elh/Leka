"""Workflows run (LEKA-397) — end to end, over HTTP and through the worker's
entry point, on Acme's company model (test_knowledge_graph).

What these protect:
- The incident review runs end to end on an intention: LEKA's own analyses,
  one after the other in the order of their dependencies — what changed
  before it skipped when an incident is explained — each step's state, what
  it found, every event kept; the workflow listed with its steps, and in the
  catalogue as a capability of kind workflow.
- Branching and failures, a step's executor scripted: a code found runs the
  branch it opens; a step failing is tried again while its attempts last;
  one that stops the workflow fails it, what was not run not reached; one
  that may fail is passed; a failed run retried goes on from where it
  failed — what succeeded not run again.
- Refused before anything is kept, said why: no such workflow, a capability
  that is not one, what it takes not given, LEKA's own steps without an
  intention. Cancelled by who asked, never by another member; retried only
  when it failed.
- The sweep fails what no worker will finish; an event is never changed;
  another workspace sees nothing.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from leka.api import workflows as workflows_api
from leka.capabilities import (
    Kind,
    StepCall,
    StepResult,
    execute_workflow,
    sweep_workflows,
    sync_catalogue,
)
from leka.capabilities import workflow_runs as engine
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity, error_fields
from tests.test_context_engine import model
from tests.test_intention_decisions_api import queued  # noqa: F401 — a fixture
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1"
REVIEW = "incident-review"


@pytest.fixture(autouse=True)
def workflows_queued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """No worker here: the tests run each run themselves."""
    runs: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        runs.append(run_id)
        return True

    monkeypatch.setattr(workflows_api, "queue_workflow", queue)
    return runs


async def _intention(client: AsyncClient, words: str = "Pourquoi Billing API est lente ?") -> str:
    created = await client.post(f"{API}/intentions", json={"text": words})
    assert created.status_code == 201, created.text
    found: str = created.json()["intention"]["id"]
    return found


async def _start(client: AsyncClient, key: str = REVIEW, **body: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/workflow-runs", json={"key": key, **body})
    assert response.status_code == 202, response.text
    started: dict[str, Any] = response.json()
    return started


async def _detail(client: AsyncClient, run_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/workflow-runs/{run_id}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def _steps(detail: dict[str, Any]) -> dict[str, str]:
    return {s["step"]: s["status"] for s in detail["steps"]}


async def _run(acme: dict[str, uuid.UUID], run_id: str) -> dict[str, object]:
    return await execute_workflow(acme["acme"], uuid.UUID(run_id))


async def _sql(workspace: uuid.UUID, statement: str, **params: Any) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(text(statement), params)
            await session.commit()


Script = dict[str, list[StepResult]]


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> Callable[[Script], list[str]]:
    """LEKA's own steps, scripted: what each attempt of each step says."""

    def install(script: Script) -> list[str]:
        called: list[str] = []

        async def run(call: StepCall) -> StepResult:
            called.append(call.step.id)
            said = script.get(call.step.id) or [StepResult("succeeded")]
            return said.pop(0) if len(said) > 1 else said[0]

        monkeypatch.setitem(engine._executors, Kind.RULES, run)
        return called

    return install


# ── end to end ─────────────────────────────────────────────────────────────


async def test_an_incident_review_runs_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    workflows_queued: list[uuid.UUID],
) -> None:
    await sync_catalogue()
    listed = (await client.get(f"{API}/workflows")).json()
    review = next(w for w in listed if w["key"] == REVIEW)
    assert [s["id"] for s in review["steps"]] == [
        "incidents",
        "changes",
        "ownership",
        "documentation",
    ]
    assert review["steps"][1]["when"] == {
        "any": [
            {"step": "incidents", "found": "incident.no_cause"},
            {"step": "incidents", "status": ["failed"]},
        ]
    }
    assert review["available"] is True, review["reasons"]
    kinds = {c["key"]: c["kind"] for c in (await client.get(f"{API}/capabilities")).json()}
    assert kinds[REVIEW] == "workflow"

    intention = await _intention(client)
    started = await _start(client, intention_id=intention)
    assert started["status"] == "queued"
    assert workflows_queued == [uuid.UUID(started["id"])]

    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    assert await _run(acme, started["id"]) == {"status": "not_queued"}
    done = await _detail(client, started["id"])
    assert done["status"] == "succeeded"
    steps = _steps(done)
    assert steps["incidents"] == "succeeded"
    assert steps["ownership"] == "succeeded"
    assert steps["documentation"] in ("succeeded", "failed")
    # What changed before it is looked for only when nothing explains it.
    incidents = next(s for s in done["steps"] if s["step"] == "incidents")
    explained = "incident.no_cause" not in incidents["output"]["codes"]
    assert steps["changes"] == ("skipped" if explained else "succeeded")
    kinds_seen = [e["kind"] for e in done["events"]]
    assert kinds_seen[:3] == ["queued", "started", "step_started"]
    assert kinds_seen[-1] == "succeeded"


# ── branching, failures, retries ───────────────────────────────────────────


async def test_a_branch_a_failure_and_a_retry_from_where_it_failed(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    scripted: Callable[[Script], list[str]],
) -> None:
    await sync_catalogue()
    intention = await _intention(client)
    called = scripted(
        {
            "incidents": [StepResult("succeeded", codes=("incident.no_cause",))],
            # Twice what it is allowed: retried while it lasts, never more.
            "ownership": [StepResult("failed", error="TimeoutError")],
        }
    )
    run = await _start(client, intention_id=intention)
    assert await _run(acme, run["id"]) == {"status": "failed", "error": "step_failed"}
    failed = await _detail(client, run["id"])
    assert (failed["failed_step"], failed["retryable"]) == ("ownership", True)
    assert _steps(failed) == {
        "incidents": "succeeded",
        "changes": "succeeded",  # the branch nothing explained opened
        "ownership": "failed",
        "documentation": "not_reached",
    }
    assert called == ["incidents", "changes", "ownership"]
    ownership = next(s for s in failed["steps"] if s["step"] == "ownership")
    assert (ownership["attempts"], ownership["reason"]) == (1, "TimeoutError")
    assert [e["kind"] for e in failed["events"]][-2:] == ["step_failed", "failed"]

    # Retried, from where it failed: what succeeded is not run again.
    called = scripted({})
    again = await client.post(f"{API}/workflow-runs/{run['id']}/retry")
    assert again.status_code == 202, again.text
    assert again.json()["retries"] == 1
    assert await _run(acme, run["id"]) == {"status": "succeeded"}
    assert called == ["ownership", "documentation"]
    retried = await _detail(client, run["id"])
    assert set(_steps(retried).values()) == {"succeeded"}
    assert "retried" in [e["kind"] for e in retried["events"]]
    assert (await client.post(f"{API}/workflow-runs/{run['id']}/retry")).status_code == 409


async def test_attempts_retry_a_step_and_a_failure_that_may_be_is_passed(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    scripted: Callable[[Script], list[str]],
) -> None:
    await sync_catalogue()
    intention = await _intention(client)
    called = scripted(
        {
            # incidents may be tried twice: the second attempt answers.
            "incidents": [StepResult("failed", error="TimeoutError"), StepResult("succeeded")],
            # documentation never stops the review.
            "documentation": [StepResult("failed", error="no_material", retryable=False)],
        }
    )
    run = await _start(client, intention_id=intention)
    assert await _run(acme, run["id"]) == {"status": "succeeded"}
    done = await _detail(client, run["id"])
    assert _steps(done) == {
        "incidents": "succeeded",
        "changes": "skipped",
        "ownership": "succeeded",
        "documentation": "failed",
    }
    assert called == ["incidents", "incidents", "ownership", "documentation"]
    incidents = next(s for s in done["steps"] if s["step"] == "incidents")
    assert incidents["attempts"] == 2
    assert "step_retried" in [e["kind"] for e in done["events"]]
    changes = next(s for s in done["steps"] if s["step"] == "changes")
    assert changes["reason"] == "condition_false"


# ── refused, cancelled ─────────────────────────────────────────────────────


async def test_refused_before_anything_is_kept_and_cancelled_by_who_asked(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    await sync_catalogue()

    async def refused(body: dict[str, Any]) -> Any:
        return await client.post(f"{API}/workflow-runs", json=body)

    assert (await refused({"key": "nothing-like-this"})).status_code == 404
    assert (await refused({"key": "ownership"})).status_code == 404
    alone = await refused({"key": REVIEW})
    assert alone.status_code == 422
    assert error_fields(alone) == {"intention_id": "required"}
    wrong = await refused({"key": "architecture-dossier", "inputs": {"deck": "yes"}})
    assert wrong.status_code == 422
    assert error_fields(wrong) == {
        "inputs.parcours": "missing",
        "inputs.perimetre": "missing",
        "inputs.deck": "type",
    }
    assert (await refused({"key": REVIEW, "intention_id": str(uuid.uuid4())})).status_code == 404
    assert (await client.get(f"{API}/workflow-runs")).json() == []

    intention = await _intention(client)
    mine = await _start(client, intention_id=intention)
    _as(identity, acme, "admin")
    theirs = await _start(client, intention_id=intention)
    _as(identity, acme, "member")
    assert (await client.post(f"{API}/workflow-runs/{theirs['id']}/cancel")).status_code == 403
    cancelled = await client.post(f"{API}/workflow-runs/{mine['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert await _run(acme, mine["id"]) == {"status": "not_queued"}
    assert set(_steps(await _detail(client, mine["id"])).values()) == {"not_reached"}
    assert (await client.post(f"{API}/workflow-runs/{mine['id']}/cancel")).status_code == 409
    assert (await client.post(f"{API}/workflow-runs/{mine['id']}/retry")).status_code == 409


# ── kept ───────────────────────────────────────────────────────────────────


async def test_swept_kept_and_the_workspace_s_own(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    await sync_catalogue()
    intention = await _intention(client)
    lost = await _start(client, intention_id=intention)
    await _sql(
        acme["acme"],
        "UPDATE workflow_runs SET status = 'running', started_at = :at WHERE id = :r",
        at=datetime.now(UTC) - timedelta(hours=3),
        r=lost["id"],
    )
    assert (await sweep_workflows())["abandoned"] >= 1
    said = await _detail(client, lost["id"])
    assert (said["status"], said["error"], said["retryable"]) == ("failed", "abandoned", True)
    assert set(_steps(said).values()) == {"not_reached"}

    with pytest.raises(DBAPIError, match="append-only"):
        await _sql(acme["acme"], "UPDATE workflow_run_events SET kind = 'succeeded'")

    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/workflow-runs/{lost['id']}")).status_code == 404
    assert (await client.get(f"{API}/workflow-runs")).json() == []
