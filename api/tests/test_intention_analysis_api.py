"""Intentions analysed, end to end (LEKA-388): from its assembled context to
a result, kept, the intention moved on.

Acme's company model (test_knowledge_graph): Billing API, of Billing
platform, owned by Payments; Checkout depends on it; Invoicing relies on
Billing platform. Nora's member asks; the admin may approve.

What these protect:
- Representative intentions execute end to end: « Qui est responsable de
  Billing API ? » answered — its owner, the record that says so —
  completed; « Qu'est-ce qui dépend de Billing API ? » — Checkout, Shop,
  Invoicing, high; « Redémarre Billing API » awaits a person's decision,
  what it reaches said — orchestrated (LEKA-399): it reads who owns it,
  handed on by the capability that found it, and says whom to tell.
- Evidence keeps its provenance: the source, its kind and name, the record.
- A context that cannot ground it is not analysed: the analysis says so,
  it stays analysing.
- A capability that fails, or exceeds its budget, is said, the others go
  on; nothing that ran is failed, and the intention with it — analysed
  again, it is retried.
- An intention that moved on meanwhile is not moved by a late analysis.
- Asked and asked again, its analysis is queued; the sweep runs what no
  job did; a member reads, another workspace sees nothing.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from leka.api import intentions as intentions_api
from leka.db import session_factory, workspace_scope
from leka.intentions import (
    Actor,
    Intention,
    IntentionRepository,
    IntentionService,
    IntentionStatus,
    processing,
)
from leka.intentions.analysis import Capability, Material, Output
from leka.intentions.capabilities import CAPABILITIES
from leka.intentions.processing import analyse_intention, analyse_pending
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/intentions"


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, str]]:
    asked: list[tuple[uuid.UUID, str]] = []

    async def queue(
        workspace_id: uuid.UUID, intention_id: uuid.UUID, *, trigger: str, by: object = None
    ) -> bool:
        asked.append((intention_id, trigger))
        return True

    monkeypatch.setattr(intentions_api, "queue_analysis", queue)
    return asked


async def _ask(client: AsyncClient, words: str, **scope: Any) -> dict[str, Any]:
    response = await client.post(API, json={"text": words, **scope})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()["intention"]
    return created


async def _get(client: AsyncClient, path: str, code: int = 200) -> Any:
    response = await client.get(f"{API}{path}")
    assert response.status_code == code, response.text
    return response.json()


async def _analysed(
    acme: dict[str, uuid.UUID], intention: dict[str, Any], **kwargs: Any
) -> dict[str, object]:
    return await analyse_intention(
        acme["acme"], uuid.UUID(intention["id"]), trigger="created", **kwargs
    )


def _codes(analysis: dict[str, Any]) -> list[str]:
    return [f["code"] for f in analysis["result"]["findings"]]


# ── representative intentions ────────────────────────────────────────────────


async def test_an_owner_question_is_answered_with_the_record_that_says_so(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    assert queued == [(uuid.UUID(intention["id"]), "created")]

    outcome = await _analysed(acme, intention)
    assert outcome["status"] == "complete"

    analysis = await _get(client, f"/{intention['id']}/analysis")
    chosen = {c["name"]: c["reason"] for c in analysis["selection"] if c["chosen"]}
    assert chosen == {"standing": "always", "ownership": "goal"}
    # No model here: the synthesis waits for one, said (LEKA-394).
    assert [(s["name"], s["status"]) for s in analysis["steps"]] == [
        ("standing", "succeeded"),
        ("ownership", "succeeded"),
        ("synthesis", "skipped"),
    ]
    # Read as its context was judged when asked (LEKA-387).
    assert (analysis["number"], analysis["trigger"], analysis["readiness"]) == (
        1,
        "created",
        intention["readiness"]["status"],
    )
    owner = next(f for f in analysis["result"]["findings"] if f["code"] == "ownership.owner")
    assert owner["params"]["owners"] == ["Payments"]
    evidence = {e["id"]: e for e in analysis["result"]["evidence"]}
    [said] = [evidence[i] for i in owner["evidence"]]
    # Where it came from: the catalogue that states the team.
    assert said["sources"] and said["sources"][0]["name"] == "Catalogue"
    assert said["origin"] == "stated"
    assert said["params"] == {"from": "Billing API", "to": "Payments"}

    # A question answered: completed, its summary said.
    after = await _get(client, f"/{intention['id']}")
    assert (after["status"], after["summary"]) == (
        "completed",
        "Billing API is owned by Payments.",
    )
    history = await _get(client, f"/{intention['id']}/history")
    moved = history[-1]
    assert (moved["name"], moved["actor"], moved["detail"]["status"]) == (
        "answered",
        "system",
        "complete",
    )


async def test_what_relies_on_it_and_what_that_reaches(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Qu'est-ce qui dépend de Billing API ?")
    await _analysed(acme, intention)

    analysis = await _get(client, f"/{intention['id']}/analysis")
    result = analysis["result"]
    relied = next(f for f in result["findings"] if f["code"] == "dependency.relied_on")
    assert relied["params"]["names"] == ["Checkout"]
    areas = {a["code"]: [i["name"] for i in a["items"]] for a in result["impact"]}
    assert areas["dependents"] == ["Checkout"]
    assert "Invoicing" in areas.get("capabilities", [])
    assert result["risk"] == "high"
    assert result["confidence"] is not None


async def test_a_restart_waits_for_a_person_what_it_reaches_said(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Redémarre Billing API en production", environment="production")
    assert intention["status"] == "analysing", intention
    await _analysed(acme, intention)

    analysis = await _get(client, f"/{intention['id']}/analysis")
    codes = _codes(analysis)
    assert "action.asked" in codes and "action.reach" in codes
    asked = next(f for f in analysis["result"]["findings"] if f["code"] == "action.asked")
    assert asked["params"]["action"] == "restart"
    # Orchestrated (LEKA-399): what it reads ran before it, together; it was
    # handed who owns what it acts on — whom to tell — and the plan is kept.
    steps = {s["name"]: s for s in analysis["steps"]}
    assert steps["ownership"]["level"] == 0 and steps["action"]["level"] == 1
    assert "ownership" in steps["action"]["handed"]
    inform = next(f for f in analysis["result"]["findings"] if f["code"] == "action.inform")
    assert inform["params"]["owners"] == ["Payments"]
    planned = analysis["detail"]["orchestration"]
    assert planned["levels"][0] and "action" in planned["levels"][1]
    # Never LEKA's to decide: a person does.
    after = await _get(client, f"/{intention['id']}")
    assert after["status"] == "awaiting_decision"
    assert "approved" in after["moves"]


async def test_a_question_its_context_cannot_ground_is_answered_what_is_missing_said(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    # A diagnosis no source can ground (LEKA-387): no_source_for — said with
    # it, and the question answered anyway: never left analysing.
    intention = await _ask(client, "Pourquoi Billing API est lente depuis hier ?")
    assert intention["status"] == "analysing"
    ready = intention["readiness"]
    assert ready["status"] == "limited"
    assert ready["critical"][0]["kind"] == "no_source_for"
    outcome = await _analysed(acme, intention)

    assert outcome["status"] != "blocked"
    analysis = await _get(client, f"/{intention['id']}/analysis")
    assert analysis["readiness"] == "limited"
    assert analysis["steps"]
    assert (await _get(client, f"/{intention['id']}"))["status"] == "completed"


async def test_an_action_its_context_cannot_ground_is_asked_to_be_clarified(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Redémarre Billing API en production")
    # Its context judged unable to ground it — two owners of what it acts on.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            row = await session.get(Intention, uuid.UUID(intention["id"]))
            assert row is not None and row.readiness is not None
            row.readiness = {
                **row.readiness,
                "status": "blocked",
                "critical": [
                    {
                        "origin": "conflict",
                        "kind": "competing",
                        "severity": "critical",
                        "said": "Two teams own Billing API.",
                        "refs": [],
                    }
                ],
            }
            await session.commit()
    outcome = await _analysed(acme, intention)

    assert outcome["status"] == "blocked"
    analysis = await _get(client, f"/{intention['id']}/analysis")
    assert (analysis["status"], analysis["error"], analysis["steps"]) == (
        "blocked",
        "context_blocked",
        [],
    )
    assert analysis["detail"]["critical"][0]["kind"] == "competing"
    # Never left analysing: the person is asked to clarify, told why.
    assert (await _get(client, f"/{intention['id']}"))["status"] == "needs_clarification"


# ── failures ─────────────────────────────────────────────────────────────────


def _boom(_: Material) -> Output:
    raise RuntimeError("boom")


def _slow(_: Material) -> Output:
    time.sleep(0.5)
    return Output()


async def test_a_capability_that_fails_or_times_out_is_said_the_others_go_on(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    broken = [
        *CAPABILITIES,
        Capability("boom", 1, ".", goals=frozenset({"find_owner"}), run=_boom),
        Capability("slow", 1, ".", goals=frozenset({"find_owner"}), run=_slow, budget=0.05),
    ]
    await _analysed(acme, intention, capabilities=broken)

    analysis = await _get(client, f"/{intention['id']}/analysis")
    steps = {s["name"]: (s["status"], s["error"]) for s in analysis["steps"]}
    assert steps == {
        "standing": ("succeeded", None),
        "ownership": ("succeeded", None),
        "boom": ("failed", "RuntimeError"),
        "slow": ("timed_out", "TimeoutError"),
        "synthesis": ("skipped", None),
    }
    assert analysis["status"] == "partial"
    assert {m["code"] for m in analysis["result"]["missing"]} == {
        "capability.failed",
        "capability.timed_out",
    }
    # Partial is still an answer.
    assert (await _get(client, f"/{intention['id']}"))["status"] == "completed"


async def test_nothing_that_ran_fails_it_and_analysed_again_it_is_retried(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    only = [Capability("boom", 1, ".", goals=frozenset(), run=_boom, always=True)]
    outcome = await _analysed(acme, intention, capabilities=only)

    assert outcome["status"] == "failed"
    after = await _get(client, f"/{intention['id']}")
    assert after["status"] == "failed"
    history = await _get(client, f"/{intention['id']}/history")
    assert history[-1]["detail"]["error"] == "RuntimeError"

    response = await client.post(f"{API}/{intention['id']}/analyse")
    assert response.status_code == 202, response.text
    assert response.json() == {"queued": True}
    assert queued[-1] == (uuid.UUID(intention["id"]), "requested")
    assert (await _get(client, f"/{intention['id']}"))["status"] == "analysing"
    await analyse_intention(acme["acme"], uuid.UUID(intention["id"]), trigger="requested")
    analyses = await _get(client, f"/{intention['id']}/analyses")
    assert [(a["number"], a["status"]) for a in analyses] == [(2, "complete"), (1, "failed")]

    # Completed, it is asked again rather than analysed again.
    refused = await client.post(f"{API}/{intention['id']}/analyse")
    assert refused.status_code == 409


async def test_a_late_analysis_moves_nothing_that_moved_on(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    reading = processing._material

    async def cancelled_meanwhile(*args: Any, **kwargs: Any) -> Material:
        with workspace_scope(acme["acme"]):
            async with session_factory() as session:
                await IntentionService(IntentionRepository(session, acme["acme"])).move(
                    uuid.UUID(intention["id"]),
                    IntentionStatus.CANCELLED,
                    actor=Actor.PERSON,
                    by=acme["member"],
                )
                await session.commit()
        return await reading(*args, **kwargs)

    monkeypatch.setattr(processing, "_material", cancelled_meanwhile)
    outcome = await _analysed(acme, intention)

    assert outcome["superseded"] is True
    assert (await _get(client, f"/{intention['id']}"))["status"] == "cancelled"
    analysis = await _get(client, f"/{intention['id']}/analysis")
    assert analysis["detail"]["superseded"] is True


async def test_a_late_analysis_of_an_old_context_version_is_superseded_and_swept(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    old_version = intention["readiness"]["version"]
    reading = processing._material
    reasked: dict[str, Any] = {}

    async def reasked_while_reading(*args: Any, **kwargs: Any) -> Material:
        response = await client.post(
            f"{API}/{intention['id']}/ask", json={"text": "Qui maintient Billing API ?"}
        )
        assert response.status_code == 200, response.text
        updated = response.json()["intention"]
        reasked["version"] = updated["readiness"]["version"]
        reasked["context_id"] = updated["context_id"]
        return await reading(*args, **kwargs)

    monkeypatch.setattr(processing, "_material", reasked_while_reading)
    outcome = await _analysed(acme, intention)

    assert outcome["superseded"] is True
    assert reasked["context_id"] == intention["context_id"]
    assert reasked["version"] > old_version
    assert (await _get(client, f"/{intention['id']}"))["status"] == "analysing"

    # The old run must not satisfy the sweep for the new version.
    monkeypatch.setattr(processing, "_material", reading)
    swept = await analyse_pending()
    assert swept["analysed"] == 1
    assert (await _get(client, f"/{intention['id']}"))["status"] == "completed"
    analyses = await _get(client, f"/{intention['id']}/analyses")
    assert [item["context_version"] for item in analyses] == [reasked["version"], old_version]
    assert analyses[0]["status"] == "complete"
    assert analyses[1]["detail"]["superseded"] is True


# ── queued, swept, read ──────────────────────────────────────────────────────


async def test_asked_again_it_is_queued_and_the_sweep_runs_what_waits(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    response = await client.post(
        f"{API}/{intention['id']}/ask", json={"text": "Qui maintient Billing API ?"}
    )
    assert response.status_code == 200, response.text
    assert [t for _, t in queued] == ["created", "asked_again"]

    # No worker took them: the sweep does.
    swept = await analyse_pending()
    assert swept["analysed"] >= 1
    assert (await _get(client, f"/{intention['id']}"))["status"] == "completed"
    again = await analyse_pending()
    assert again == {"analysed": 0, "blocked": 0, "failed": 0}


async def test_a_member_reads_another_workspace_sees_nothing(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    await _get(client, f"/{intention['id']}/analysis", code=404)
    await _analysed(acme, intention)
    assert (await _get(client, f"/{intention['id']}/analysis"))["status"] == "complete"

    _as(identity, acme, "other_admin")
    await _get(client, f"/{intention['id']}/analysis", code=404)
    await _get(client, f"/{intention['id']}/analyses", code=404)
    assert (await client.post(f"{API}/{intention['id']}/analyse")).status_code == 404


def test_the_job_entry_reads_its_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake(
        workspace_id: uuid.UUID, intention_id: uuid.UUID, **kwargs: Any
    ) -> dict[str, object]:
        seen.update(workspace=workspace_id, intention=intention_id, **kwargs)
        return {"status": "complete"}

    monkeypatch.setattr(processing, "analyse_intention", fake)
    workspace, intention, by = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert processing.run_analysis(str(workspace), str(intention), "requested", str(by)) == {
        "status": "complete"
    }
    assert seen == {
        "workspace": workspace,
        "intention": intention,
        "trigger": "requested",
        "by": by,
    }
