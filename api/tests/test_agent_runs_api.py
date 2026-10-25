"""Agents, run (LEKA-395) — end to end, over HTTP and through the worker's
entry point, on Acme's company model (test_knowledge_graph); LEKA holds a
Gemini key, and what Gemini says is scripted.

What these protect:
- The application architect runs end to end: asked by a member, queued,
  run — its context assembled from what it was given, only the things it is
  about; it searches the model and reads it with its tools, a thing it is
  not about refused, a tool it made up answered unknown — each call kept;
  the model asked through the gateway, its rules before the agent's
  instructions, each call kept with the run; what it delivered kept; its
  deck written from its analysis — asked again of the model, structured,
  no tools — then drawn: its PowerPoint and PDF kept and downloadable by
  whoever may read the run, nobody else's; every step readable, what its
  calls took. The catalogue now says agents run.
- A deck the model cannot write never fails the run: its analysis stands,
  said why its files are missing.
- Refused before anything is kept, said why: no such agent, not an agent,
  not usable here (no source to read, a draft), what it takes not given,
  a context or an intention that is not the workspace's — and an agent
  whose permission the person's role lacks (403).
- Its tools follow who asked: a tool that acts is never offered, one the
  person may not use neither — said in its steps, never declared to the
  model.
- As things stand when it runs: a person no longer in the workspace, an
  agent turned off meanwhile — failed, said why.
- Failures said: no model answering, a model asking for tools forever, a
  run past its budget.
- Cancelled by who asked or an admin, never by another member; a cancelled
  run is not run; an ended one cannot be cancelled.
- The sweep fails what no worker will finish; a step is never changed;
  another workspace sees nothing.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import asyncio
import importlib
import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pptx import Presentation
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from leka.api import agent_runs as agent_runs_api
from leka.capabilities import (
    AGENT_TOOLS,
    AgentTool,
    Gateway,
    ModelCall,
    execute_run,
    find,
    redraw,
    sweep_runs,
    sync_catalogue,
)
from leka.capabilities.deliverables.layout import deck_slides
from leka.capabilities.gateway import service
from leka.capabilities.registry import catalogue
from leka.capabilities.runs import TOOL_ROUNDS
from leka.core.config import settings
from leka.db import session_factory, system_scope, workspace_scope
from leka.platform import LocalObjectStore, storage
from tests.conftest import FakeIdentity, error_code, error_fields
from tests.test_capabilities_api import _connect
from tests.test_context_engine import model
from tests.test_deliverables import deck as drawn_deck
from tests.test_knowledge_graph import BILLING, INVOICING
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

# The architect asks for its rounds (2026-10-14: it reads a whole
# documentation before it draws); the runtime's default otherwise.
# Every read-only tool, as an agent that declares none is offered them.
TOOL_NAMES = ["search_entities", "read_entity", "dependencies", "what_happened", "read_content"]
ROUNDS = {d.key: d for d in catalogue()}["application-architecture"].rounds or TOOL_ROUNDS

pytestmark = pytest.mark.integration

# The module: the package's `catalogue` is its function.
catalogue_module = importlib.import_module("leka.capabilities.catalogue")

_ = model  # a fixture, requested by name
API = "/api/v1/agent-runs"
ARCHITECT = "application-architecture"
ASKED = {"parcours": "Billing API", "perimetre": "Checkout"}


def gemini(text: str | None = None, call: dict[str, Any] | None = None) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    if text is not None:
        parts.append({"text": text})
    if call is not None:
        parts.append({"functionCall": call, "thoughtSignature": "sig-1"})
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 300},
        "modelVersion": "gemini-3.8-flash-001",
        "responseId": "resp-1",
    }


class Script:
    """What Gemini says, in order — and what it was asked."""

    def __init__(self, *answers: dict[str, Any] | httpx.Response) -> None:
        self.answers = list(answers)
        self.asked: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(json.loads(request.content))
        answer = self.answers.pop(0)
        return answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)

    def declared(self, asked: int = 0) -> list[str]:
        tools = self.asked[asked].get("tools") or [{"functionDeclarations": []}]
        return [d["name"] for d in tools[0]["functionDeclarations"]]


@pytest.fixture
def leka_gemini(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Script]:
    """LEKA holds a Gemini key; what it says, scripted."""
    configured = settings.model_copy(
        update={
            "google_api_key": SecretStr("g-key"),
            "mistral_api_key": None,
            "anthropic_api_key": None,
            "llm_fallbacks": "",
        }
    )
    monkeypatch.setattr(service, "settings", configured)

    def install(*answers: dict[str, Any] | httpx.Response) -> Script:
        scripted = Script(*answers)
        monkeypatch.setattr(
            Gateway,
            "_client",
            lambda self, endpoint, tier: httpx.AsyncClient(transport=httpx.MockTransport(scripted)),
        )
        return scripted

    return install


@pytest.fixture(autouse=True)
def queued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """No worker here: the tests run each run themselves."""
    runs: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        runs.append(run_id)
        return True

    monkeypatch.setattr(agent_runs_api, "queue_run", queue)
    return runs


async def _ready(acme: dict[str, uuid.UUID]) -> None:
    """The catalogue registered, a source the architect reads connected."""
    await sync_catalogue()
    await _connect(acme, "confluence")


async def _start(client: AsyncClient, key: str = ARCHITECT, **body: Any) -> dict[str, Any]:
    response = await client.post(API, json={"key": key, "inputs": ASKED, **body})
    assert response.status_code == 202, response.text
    started: dict[str, Any] = response.json()
    return started


async def _detail(client: AsyncClient, run_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/{run_id}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


async def _run(acme: dict[str, uuid.UUID], run_id: str, **kwargs: Any) -> dict[str, object]:
    return await execute_run(acme["acme"], uuid.UUID(run_id), **kwargs)


def _kinds(detail: dict[str, Any]) -> list[str]:
    return [e["kind"] for e in detail["events"]]


async def _sql(workspace: uuid.UUID, statement: str, **params: Any) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(text(statement), params)
            await session.commit()


# ── end to end ─────────────────────────────────────────────────────────────


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> LocalObjectStore:
    """Where the decks are kept: a directory of the test's."""
    local = LocalObjectStore(tmp_path)
    monkeypatch.setattr(storage, "_store", local)
    return local


async def test_the_architect_runs_end_to_end(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    queued: list[uuid.UUID],
    store: LocalObjectStore,
) -> None:
    await _ready(acme)
    deck = f"# Architecture — Billing API\n\nBilling API [{model[BILLING]}] sert Checkout."
    content = drawn_deck(app_view=False)
    script = leka_gemini(
        gemini(call={"name": "search_entities", "args": {"query": "billing"}}),
        gemini(call={"name": "read_entity", "args": {"id": str(model[INVOICING])}}),
        gemini(call={"name": "delete_everything", "args": {}}),
        gemini(deck),
        gemini(content.model_dump_json()),
    )
    # The catalogue says agents run: nothing in the architect's way.
    catalogue = (await client.get("/api/v1/capabilities")).json()
    architect = next(c for c in catalogue if c["key"] == ARCHITECT)
    assert architect["available"] is True and architect["reasons"] == []

    started = await _start(client)
    # Its PowerPoint and PDF, LEKA draws: nothing pending.
    assert (started["status"], started["format"], started["pending"]) == (
        "queued",
        "markdown",
        [],
    )
    assert (started["title"], started["version"], started["mine"]) == (
        "Architecte applicatif",
        "19.3.0",
        True,
    )
    assert started["deliverables"] == []
    assert queued == [uuid.UUID(started["id"])]

    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    # Run once: a run no longer queued is not run again.
    assert await _run(acme, started["id"]) == {"status": "not_queued"}

    done = await _detail(client, started["id"])
    assert done["status"] == "succeeded"
    assert done["output"] == deck
    assert (done["provider"], done["model"], done["model_version"]) == (
        "google",
        "gemini-3.8-flash",
        "gemini-3.8-flash-001",
    )
    assert done["tool_calls"] == 3
    assert done["context_id"] is not None and done["context_version"] == 1
    assert _kinds(done) == [
        "queued",
        "started",
        "context",
        # No repository connected: its reading of the code, said withheld.
        "tool_withheld",
        "tool_withheld",
        "tool",
        "tool",
        "tool",
        "answered",
        "rendered",
        "succeeded",
    ]
    rendered = next(e["detail"] for e in done["events"] if e["kind"] == "rendered")
    slides = len(deck_slides(content))
    assert (rendered["formats"], rendered["slides"]) == (["pptx", "pdf"], slides)
    name = "Architecture applicative - Parcours Paiement CB"
    assert [(d["format"], d["name"], d["slides"]) for d in done["deliverables"]] == [
        ("pptx", f"{name}.pptx", slides),
        ("pdf", f"{name}.pdf", slides),
    ]
    context = done["events"][2]["detail"]
    assert context["given"] > 0
    called = [e for e in done["events"] if e["kind"] == "tool"]
    tools = [(e["detail"]["name"], e["detail"]["outcome"]) for e in called]
    assert tools == [
        ("search_entities", "ok"),
        ("read_entity", "refused"),
        ("delete_everything", "unknown"),
    ]
    assert called[1]["detail"]["why"] == "out_of_scope"
    assert done["usage"]["calls"] == 5
    assert done["usage"]["tokens_in"] == 5000
    # An agent's instructions never leave the server.
    assert "PRINCIPE ABSOLU" not in json.dumps(done)

    # What the model was given: LEKA's rules, then the agent's.
    system = script.asked[0]["systemInstruction"]["parts"][0]["text"]
    assert system.index("read-only") < system.index("PRINCIPE ABSOLU")
    # It declares none: every read-only tool (LEKA-400).
    assert script.declared() == TOOL_NAMES
    given = json.loads(script.asked[0]["contents"][0]["parts"][0]["text"])
    assert given["inputs"] == ASKED
    assert all(e["type"] != "business_capability" for e in given["context"])
    # What its search found: only what it is about.
    found = script.asked[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert "Billing API" in found and "Invoicing" not in found

    # Every call kept, with the run.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            calls = (
                await session.scalars(
                    select(ModelCall).where(ModelCall.ref == f"agent_run:{started['id']}")
                )
            ).all()
    assert {(c.purpose, c.tier, c.status) for c in calls} == {
        ("agent:application-architecture", "deep", "ok"),
        ("agent:application-architecture:deck", "deep", "ok"),
    }

    # The deck: asked structured, with no tool, its writer's rules before the
    # agent's template; the analysis given as data.
    asked = script.asked[4]
    assert asked["generationConfig"]["responseMimeType"] == "application/json"
    assert "tools" not in asked
    writer = asked["systemInstruction"]["parts"][0]["text"]
    assert writer.index("deck writer") < writer.index("PRINCIPE ABSOLU")
    assert json.loads(asked["contents"][0]["parts"][0]["text"])["analysis"] == deck

    # Its files, downloadable by whoever may read the run.
    pdf = await client.get(f"{API}/{started['id']}/deliverables/pdf")
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    disposition = pdf.headers["content-disposition"]
    assert disposition.startswith("attachment;") and "Paiement%20CB.pdf" in disposition
    pptx = await client.get(f"{API}/{started['id']}/deliverables/pptx")
    assert pptx.status_code == 200
    assert len(Presentation(BytesIO(pptx.content)).slides) == slides
    # A format runs deliver, this one did not: none; one they never do: refused.
    assert (await client.get(f"{API}/{started['id']}/deliverables/docx")).status_code == 404
    assert (await client.get(f"{API}/{started['id']}/deliverables/exe")).status_code == 422
    assert (await client.get(f"{API}/{uuid.uuid4()}/deliverables/pdf")).status_code == 404
    # Kept under the run, in the workspace.
    kept = [key async for key in store.iter_prefix(f"{acme['acme']}/agent-runs/")]
    assert sorted(kept) == [
        f"{acme['acme']}/agent-runs/{started['id']}/deck.pdf",
        f"{acme['acme']}/agent-runs/{started['id']}/deck.pptx",
    ]

    listed = (await client.get(API, params={"key": ARCHITECT})).json()
    assert [r["id"] for r in listed] == [started["id"]]
    assert (await client.get(API, params={"status": "failed"})).json() == []


async def test_a_report_alone_then_its_deck_drawn_after_it_never_run_again(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    queued: list[uuid.UUID],
    store: LocalObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-10-16: launched without asking for files, the architect gave its
    report alone. Its deck is drawn after it, from what it delivered."""
    await _ready(acme)
    analysis = f"# Architecture — Billing API\n\nBilling API [{model[BILLING]}] sert Checkout."
    content = drawn_deck(app_view=False)
    leka_gemini(gemini(analysis), gemini(content.model_dump_json()))
    asked: list[tuple[uuid.UUID, list[str]]] = []

    async def files(workspace_id: uuid.UUID, run_id: uuid.UUID, formats: list[str]) -> bool:
        asked.append((run_id, list(formats)))
        return True

    monkeypatch.setattr(agent_runs_api, "queue_files", files)
    started = await _start(client)
    # Launched from an intention asking for no file (as it is kept then).
    await _sql(
        acme["acme"],
        "UPDATE agent_runs SET detail = detail || '{\"formats\": []}'::jsonb WHERE id = :id",
        id=uuid.UUID(started["id"]),
    )
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    done = await _detail(client, started["id"])
    assert (done["deliverables"], done["expected"]) == ([], [])
    assert done["drawable"] == ["pdf", "pptx"]

    drawing = await client.post(f"{API}/{started['id']}/files", json={"formats": ["pdf", "pptx"]})
    assert drawing.status_code == 202, drawing.text
    assert drawing.json()["drawing"] == ["pdf", "pptx"]
    assert asked == [(uuid.UUID(started["id"]), ["pdf", "pptx"])]
    # Asked twice while drawn: refused.
    again = await client.post(f"{API}/{started['id']}/files", json={"formats": ["pdf"]})
    assert again.status_code == 409

    # The worker draws them from its analysis — the run itself not done again.
    said = await redraw(acme["acme"], uuid.UUID(started["id"]), ["pdf", "pptx"])
    assert said == {"drawn": ["pptx", "pdf"], "error": None}
    after = await _detail(client, started["id"])
    assert (after["status"], after["output"]) == ("succeeded", analysis)
    assert sorted(d["format"] for d in after["deliverables"]) == ["pdf", "pptx"]
    assert (after["drawable"], after["drawing"]) == ([], [])
    assert _kinds(after)[-1] == "rendered"
    pdf = await client.get(f"{API}/{started['id']}/deliverables/pdf")
    assert pdf.status_code == 200
    # Nothing left to draw.
    done_twice = await client.post(f"{API}/{started['id']}/files", json={"formats": ["pdf"]})
    assert done_twice.status_code == 422


async def test_files_drawn_after_never_left_waiting_failed_or_lost(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    queued: list[uuid.UUID],
    store: LocalObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-10-16: « en préparation » stayed forever. A deck the model cannot
    write ends it, said why; a request lost (no worker) is asked again."""
    await _ready(acme)
    analysis = "# Architecture — Billing API\n\nRien de plus dans les sources."
    leka_gemini(gemini(analysis), *[gemini("Voici le deck : pas de JSON.")] * 10)

    async def files(workspace_id: uuid.UUID, run_id: uuid.UUID, formats: list[str]) -> bool:
        return True

    monkeypatch.setattr(agent_runs_api, "queue_files", files)
    started = await _start(client)
    await _sql(
        acme["acme"],
        "UPDATE agent_runs SET detail = detail || '{\"formats\": []}'::jsonb WHERE id = :id",
        id=uuid.UUID(started["id"]),
    )
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    asked = await client.post(f"{API}/{started['id']}/files", json={"formats": ["pdf", "pptx"]})
    assert asked.status_code == 202, asked.text
    said = await redraw(acme["acme"], uuid.UUID(started["id"]), ["pdf", "pptx"])
    assert said["error"] == "unanswered"
    after = await _detail(client, started["id"])
    # No longer « en préparation »: why said, the way to ask again.
    assert (after["drawing"], after["draw_failed"]) == ([], "unanswered")
    assert after["drawable"] == ["pdf", "pptx"]

    # Asked, and no worker ever drew it: lost after 20 minutes — asked again.
    again = await client.post(f"{API}/{started['id']}/files", json={"formats": ["pdf"]})
    assert again.status_code == 202 and again.json()["draw_failed"] is None
    assert (await _detail(client, started["id"]))["drawing"] == ["pdf"]
    await _sql(
        acme["acme"],
        "UPDATE agent_runs SET detail = detail || "
        "jsonb_build_object('drawing_since', (now() - interval '25 minutes')::text) "
        "WHERE id = :id",
        id=uuid.UUID(started["id"]),
    )
    assert (await _detail(client, started["id"]))["drawing"] == []
    assert (
        await client.post(f"{API}/{started['id']}/files", json={"formats": ["pdf"]})
    ).status_code == 202


async def test_a_deck_the_model_cannot_write_never_fails_the_run(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    store: LocalObjectStore,
) -> None:
    await _ready(acme)
    analysis = "# Architecture — Billing API\n\nRien de plus dans les sources."
    leka_gemini(gemini(analysis), *[gemini("Voici le deck : pas de JSON.")] * 10)
    started = await _start(client)
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    done = await _detail(client, started["id"])
    # The analysis stands; why there are no files, said.
    assert (done["status"], done["output"], done["deliverables"]) == ("succeeded", analysis, [])
    assert _kinds(done)[-2:] == ["render_failed", "succeeded"]
    # Said as it was: the model answered, and not a deck — never "no model".
    assert done["events"][-2]["detail"]["code"] == "unanswered"
    assert "Invalid JSON" in done["events"][-2]["detail"]["said"]
    assert (await client.get(f"{API}/{started['id']}/deliverables/pdf")).status_code == 404
    assert [key async for key in store.iter_prefix("")] == []


async def test_an_agent_that_keeps_reading_answers_with_what_it_read(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    store: LocalObjectStore,
) -> None:
    """The architect's instructions ask it to look brick by brick: it may
    read for its rounds (ROUNDS); the last is offered no tool, and it answers
    with what it read — never a failed run for having looked too much."""
    await _ready(acme)
    asking = gemini(call={"name": "search_entities", "args": {"query": "billing"}})
    analysis = "# Architecture — Billing API\n\nCe que les sources disent."
    script = leka_gemini(
        *[asking] * (ROUNDS - 1),
        gemini(analysis),
        gemini(drawn_deck(app_view=False).model_dump_json()),
    )
    started = await _start(client)
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    done = await _detail(client, started["id"])
    assert (done["output"], done["tool_calls"]) == (analysis, ROUNDS - 1)
    # Offered tools every round but the last, which must answer.
    modes = [
        a.get("toolConfig", {}).get("functionCallingConfig", {}).get("mode") for a in script.asked
    ]
    assert modes[: ROUNDS - 1].count("NONE") == 0
    assert modes[ROUNDS - 1] == "NONE"
    assert [d["format"] for d in done["deliverables"]] == ["pptx", "pdf"]
    # Any agent's deliverable, as a PDF too (2026-10-23): drawn on demand.
    report = await client.get(f"{API}/{started['id']}/report.pdf")
    assert report.status_code == 200
    assert report.headers["content-type"] == "application/pdf"
    assert report.content.startswith(b"%PDF")
    assert (await client.get(f"{API}/{uuid.uuid4()}/report.pdf")).status_code == 404


async def test_a_model_that_ignores_no_more_tools_is_asked_with_none_declared(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    store: LocalObjectStore,
) -> None:
    """As in production: told to call no more tools on its last round, the
    model asked for one anyway. Its call is not run; it is asked once more
    with no tool declared, what it read given as text — and it answers."""
    await _ready(acme)
    asking = gemini(call={"name": "search_entities", "args": {"query": "billing"}})
    analysis = "# Architecture — Billing API\n\nCe que les sources disent."
    script = leka_gemini(
        *[asking] * ROUNDS,
        gemini(analysis),
        gemini(drawn_deck(app_view=False).model_dump_json()),
    )
    started = await _start(client)
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    done = await _detail(client, started["id"])
    assert (done["output"], done["tool_calls"]) == (analysis, ROUNDS - 1)
    final = script.asked[ROUNDS]
    assert "tools" not in final and "toolConfig" not in final
    # What it was given, then what it read — one turn, no tool exchange.
    [turn] = final["contents"]
    said = turn["parts"][0]["text"]
    assert turn["role"] == "user" and said.startswith('{"inputs"')
    assert "You have used every round of tools" in said
    assert "## search_entities" in said and "Billing API" in said
    assert [d["format"] for d in done["deliverables"]] == ["pptx", "pdf"]


# ── refused ────────────────────────────────────────────────────────────────


async def test_a_run_is_refused_before_anything_is_kept(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leka_gemini()
    await sync_catalogue()

    async def refused(body: dict[str, Any]) -> httpx.Response:
        return await client.post(API, json={"inputs": ASKED, **body})

    nothing = await refused({"key": "nothing-like-this"})
    assert nothing.status_code == 404
    ownership = await refused({"key": "ownership"})
    assert ownership.status_code == 422
    # No source to read: said.
    unread = await refused({"key": ARCHITECT})
    assert unread.status_code == 422
    assert error_fields(unread) == {"key": "missing_source"}
    draft = await refused({"key": "correlate-deploy-with-latency", "inputs": {}})
    assert draft.status_code == 422
    assert "lifecycle" in json.dumps(draft.json())

    await _connect(acme, "confluence")
    wrong = await client.post(API, json={"key": ARCHITECT, "inputs": {"parcours": "", "x": 1}})
    assert wrong.status_code == 422
    assert error_fields(wrong) == {
        "inputs.x": "unknown",
        "inputs.parcours": "missing",
        "inputs.perimetre": "missing",
    }
    elsewhere = await refused({"key": ARCHITECT, "context_id": str(uuid.uuid4())})
    assert elsewhere.status_code == 422
    no_intention = await refused({"key": ARCHITECT, "intention_id": str(uuid.uuid4())})
    assert no_intention.status_code == 404
    assert (await client.get(API)).json() == []

    # An agent only who may approve may run: refused to a member, 403.
    architect = find(ARCHITECT)
    assert architect is not None
    guarded = replace(
        architect,
        key="architect-for-approvers",
        permission="intention:approve",
        dedicated=False,
    )
    every = catalogue_module.catalogue()
    monkeypatch.setattr(catalogue_module, "catalogue", lambda: (*every, guarded))
    forbidden = await refused({"key": "architect-for-approvers"})
    assert forbidden.status_code == 403
    assert error_code(forbidden) == "permission_denied"
    _as(identity, acme, "admin")
    assert (await refused({"key": "architect-for-approvers"})).status_code == 202


# ── its tools follow who asked ─────────────────────────────────────────────


async def test_its_tools_follow_who_asked_and_never_act(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    await _ready(acme)
    acts = AgentTool("restart_service", "Restart a service.", {"type": "object"}, "workspace:read")
    acts = replace(acts, effect="act")
    admins = AgentTool("read_sources", "The sources.", {"type": "object"}, "source:manage")
    tools = (*AGENT_TOOLS, acts, admins)

    script = leka_gemini(gemini("# Rien à dire."))
    asked = await _start(client)
    assert await _run(acme, asked["id"], tools=tools) == {"status": "succeeded"}
    done = await _detail(client, asked["id"])
    withheld = [e["detail"] for e in done["events"] if e["kind"] == "tool_withheld"]
    assert withheld == [
        {"name": "restart_service", "why": "acts"},
        {"name": "read_sources", "why": "not_permitted"},
        # It names no tools: the code's reading too — no repository here.
        {"name": "list_files", "why": "no_source"},
        {"name": "read_file", "why": "no_source"},
    ]
    assert script.declared() == TOOL_NAMES

    _as(identity, acme, "admin")
    script = leka_gemini(gemini("# Rien à dire."))
    asked = await _start(client)
    await _run(acme, asked["id"], tools=tools)
    assert script.declared() == [
        *TOOL_NAMES,
        "read_sources",
    ]


# ── as things stand when it runs ───────────────────────────────────────────


async def test_what_changed_before_it_ran_is_heeded(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    await _ready(acme)
    leka_gemini()
    # Turned off by an admin before a worker took it.
    first = await _start(client)
    _as(identity, acme, "admin")
    off = await client.put(
        f"/api/v1/capabilities/{ARCHITECT}/settings",
        json={"enabled": False, "reason": "En revue"},
    )
    assert off.status_code == 200, off.text
    assert await _run(acme, first["id"]) == {"status": "failed", "error": "unavailable"}
    stopped = await _detail(client, first["id"])
    assert (stopped["status"], stopped["error"]) == ("failed", "unavailable")
    assert [r["code"] for r in stopped["reasons"]] == ["disabled"]
    assert _kinds(stopped) == ["queued", "started", "failed"]
    await client.put(f"/api/v1/capabilities/{ARCHITECT}/settings", json={"enabled": True})

    # Who asked left the workspace before it ran.
    _as(identity, acme, "member")
    second = await _start(client)
    await _sql(acme["acme"], "DELETE FROM memberships WHERE user_id = :u", u=acme["member"])
    assert await _run(acme, second["id"]) == {"status": "failed", "error": "not_permitted"}


# ── failures, said ─────────────────────────────────────────────────────────


async def test_failures_are_said(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _ready(acme)
    # No model answering: a refused request is not tried again.
    leka_gemini(httpx.Response(400, json={"error": {"message": "Bad request"}}))
    refused = await _start(client)
    assert await _run(acme, refused["id"]) == {"status": "failed", "error": "no_model"}
    said = await _detail(client, refused["id"])
    assert said["error"] == "no_model" and said["events"][-1]["detail"]["tried"] == 1

    # A model asking for tools, and never answering — not even when its last
    # round offers none, nor when it is asked once more with none declared.
    asking = gemini(call={"name": "search_entities", "args": {"query": "billing"}})
    leka_gemini(*[asking] * (ROUNDS + 1))
    endless = await _start(client)
    assert await _run(acme, endless["id"]) == {"status": "failed", "error": "tool_rounds"}
    # What it asked on its last round is never run.
    assert (await _detail(client, endless["id"]))["tool_calls"] == ROUNDS - 1

    # Longer than a run may take.
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json=gemini("late"))

    leka_gemini()
    monkeypatch.setattr(
        Gateway,
        "_client",
        lambda self, endpoint, tier: httpx.AsyncClient(transport=httpx.MockTransport(slow)),
    )
    late = await _start(client)
    assert await _run(acme, late["id"], budget=0.2) == {"status": "failed", "error": "timeout"}
    assert (await _detail(client, late["id"]))["finished_at"] is not None

    # Cut at its token limit mid-sentence (2026-10-20): said, never « done ».
    cut = gemini("# Revue de sécurité\n\n1. État\n\nLeka Caddy ([d4d687bc-e9c6-53")
    cut["candidates"][0]["finishReason"] = "MAX_TOKENS"
    leka_gemini(cut)
    halted = await _start(client)
    assert await _run(acme, halted["id"]) == {"status": "failed", "error": "invalid_output"}
    assert (await _detail(client, halted["id"]))["events"][-1]["detail"]["cut"] is True


# ── cancelled ──────────────────────────────────────────────────────────────


async def test_cancelled_by_who_asked_or_an_admin(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    await _ready(acme)
    leka_gemini()
    _as(identity, acme, "admin")
    theirs = await _start(client)
    _as(identity, acme, "member")
    mine = await _start(client)

    assert (await client.post(f"{API}/{theirs['id']}/cancel")).status_code == 403
    cancelled = await client.post(f"{API}/{mine['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    # Never run; and cannot be cancelled again.
    assert await _run(acme, mine["id"]) == {"status": "not_queued"}
    assert (await client.post(f"{API}/{mine['id']}/cancel")).status_code == 409
    assert _kinds(await _detail(client, mine["id"])) == ["queued", "cancelled"]

    _as(identity, acme, "admin")
    assert (await client.post(f"{API}/{theirs['id']}/cancel")).status_code == 200
    assert (await client.post(f"{API}/{uuid.uuid4()}/cancel")).status_code == 404


# ── kept ───────────────────────────────────────────────────────────────────


async def test_kept_swept_and_the_workspaces_own(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    await _ready(acme)
    leka_gemini()
    lost = await _start(client)
    forgotten = await _start(client)
    long_ago = datetime.now(UTC) - timedelta(hours=8)
    await _sql(
        acme["acme"],
        "UPDATE agent_runs SET status = 'running', started_at = :at WHERE id = :r",
        at=long_ago,
        r=lost["id"],
    )
    await _sql(
        acme["acme"],
        "UPDATE agent_runs SET queued_at = :at WHERE id = :r",
        at=long_ago,
        r=forgotten["id"],
    )
    swept = await sweep_runs()
    assert swept["abandoned"] >= 2
    for run in (lost, forgotten):
        said = await _detail(client, run["id"])
        assert (said["status"], said["error"]) == ("failed", "abandoned")
    assert (await sweep_runs())["abandoned"] == 0

    # A step is never changed.
    with pytest.raises(DBAPIError, match="append-only"):
        await _sql(acme["acme"], "UPDATE agent_run_events SET kind = 'succeeded'")

    # Another workspace sees nothing of it.
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/{lost['id']}")).status_code == 404
    assert (await client.get(API)).json() == []
    with system_scope():
        async with session_factory() as session:
            assert await session.scalar(text("SELECT count(*) FROM agent_runs")) >= 2
