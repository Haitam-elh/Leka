"""The enterprise agent library (LEKA-400) in realistic scenarios — run end
to end on Acme's company model (test_knowledge_graph), what Gemini says
scripted.

What these protect:
- An incident investigated on Billing API: routed there from what was asked,
  its context assembled from it, the investigator following what depends on
  Billing API and what happened around it with its own tools — only what it
  is about — and delivering its post-mortem; every step kept.
- An architecture explained from Checkout: what Checkout depends on, read
  with the dependencies tool; a thing it is not about refused.
- Least privilege: the documentation assistant declares only searching and
  reading — the model is offered nothing else; the build fixer, which only
  proposes, is never routed to by a question.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient

from leka.capabilities import sync_catalogue
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import (
    Script,
    _detail,
    _kinds,
    _run,
    gemini,
    leka_gemini,  # noqa: F401 — a fixture
    queued,  # noqa: F401 — a fixture
)
from tests.test_context_engine import model
from tests.test_knowledge_graph import BILLING, CHECKOUT, INVOICING
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1"


async def _start(client: AsyncClient, key: str, **inputs: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/agent-runs", json={"key": key, "inputs": inputs})
    assert response.status_code == 202, response.text
    started: dict[str, Any] = response.json()
    return started


def _answered(script: Script, asked: int) -> Any:
    """What a tool answered the model, as its next request carries it."""
    part = script.asked[asked]["contents"][-1]["parts"][0]["functionResponse"]
    return json.loads(part["response"]["result"])


async def test_an_incident_is_routed_to_the_investigator_and_investigated(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    await sync_catalogue()
    routed = await client.post(
        f"{API}/capabilities/route",
        json={
            "text": "Investigue l'incident de Billing API de cette nuit",
            "goal": "explain_cause",
            "kind": "diagnose",
        },
    )
    assert "incident-investigation" in routed.json()["selected"]

    billing = str(model[BILLING])
    report = f"# Post-mortem : Billing API\n\nCheckout dépend de Billing API [{billing}]."
    script = leka_gemini(
        gemini(call={"name": "dependencies", "args": {"id": billing, "direction": "used_by"}}),
        gemini(call={"name": "what_happened", "args": {"id": billing, "days": 7}}),
        gemini(report),
    )
    started = await _start(client, "incident-investigation", incident="incident de Billing API")
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    done = await _detail(client, started["id"])
    assert done["output"] == report
    assert _kinds(done) == ["queued", "started", "context", "tool", "tool", "answered", "succeeded"]
    assert [e["detail"]["outcome"] for e in done["events"] if e["kind"] == "tool"] == ["ok", "ok"]
    # It is offered the four tools it declares, and the skills it names (LEKA-401).
    assert script.declared() == [
        "search_entities",
        "read_entity",
        "dependencies",
        "what_happened",
        "incident-history",
        "blast-radius",
    ]
    reached = _answered(script, 1)
    assert reached["direction"] == "used_by"
    assert str(model[CHECKOUT]) in [t["id"] for t in reached["things"]]
    happened = _answered(script, 2)
    assert happened["days"] == 7 and isinstance(happened["events"], list)


async def test_an_architecture_is_read_through_its_dependencies(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    await sync_catalogue()
    checkout = str(model[CHECKOUT])
    script = leka_gemini(
        gemini(call={"name": "dependencies", "args": {"id": checkout, "direction": "depends_on"}}),
        gemini("# Architecture de Checkout\n\nCheckout s'appuie sur Billing API."),
    )
    started = await _start(client, "architecture-analysis", sujet="Checkout")
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    upstream = _answered(script, 1)
    assert str(model[BILLING]) in [t["id"] for t in upstream["things"]]
    # dependencies, never what_happened: it does not declare it — and the
    # skill it names (LEKA-401).
    assert script.declared() == ["search_entities", "read_entity", "dependencies", "blast-radius"]

    # Invoicing is a business capability: not what the debugging agent reads.
    script = leka_gemini(
        gemini(
            call={
                "name": "dependencies",
                "args": {"id": str(model[INVOICING]), "direction": "depends_on"},
            }
        ),
        gemini("# Débogage\n\nRien à dire."),
    )
    started = await _start(client, "debug-assistant", symptome="Invoicing")
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    assert _answered(script, 1) == {"error": "out_of_scope"}


async def test_least_privilege_and_no_fixing_on_a_question(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    await sync_catalogue()
    from tests.test_capabilities_api import _connect

    await _connect(acme, "confluence")
    script = leka_gemini(gemini("# Documentation de Billing API\n\nÀ compléter."))
    started = await _start(client, "documentation-assistant", sujet="Billing API")
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    assert script.declared() == ["search_entities", "read_entity", "documentation-coverage"]
    # It reads code too (2026-10-18) — only with a GitHub source: without
    # one, its code tools are kept back, and said why.
    done = await _detail(client, started["id"])
    kept = {
        e["detail"]["name"]: e["detail"]["why"]
        for e in done["events"]
        if e["kind"] == "tool_withheld"
    }
    assert kept == {"list_files": "no_source", "read_file": "no_source"}

    asked = await client.post(
        f"{API}/capabilities/route",
        json={"text": "Pourquoi le build de checkout est cassé ?", "goal": "explain_cause"},
    )
    said = asked.json()
    assert "build-fixer" not in said["selected"]
    fixer = next(c for c in said["excluded"] if c["key"] == "build-fixer")
    assert {"code": "policy", "rule": "proposes_actions_to_a_question"} in fixer["reasons"]
