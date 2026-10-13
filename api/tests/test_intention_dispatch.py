"""An intention handed to the agent that does what it asks (dispatch.py):
LEKA doing the work, not only answering — Gemini scripted, no network.

What these protect:
- « Construis l'architecture du parcours … sur le périmètre …, il me faut
  un PDF » starts the architect, for the person who asked, on the
  intention, with the parcours and the périmètre taken from their words —
  and the answer says the deck is being made, never that LEKA cannot.
- Once: analysing it again starts nothing more.
- A plain question starts nothing; an agent not offered, or a required
  input the request does not give, starts nothing.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from leka.capabilities import AgentRun, Gateway, find
from leka.capabilities.gateway import service
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from leka.intentions import dispatch as dispatch_module
from leka.intentions import feasibility as feasibility_module
from leka.intentions.dispatch import Dispatched, checked
from leka.metering import credits as metering_credits
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import _ready
from tests.test_context_engine import model
from tests.test_intention_analysis_api import _analysed, _ask, _get, queued  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name

ARCHITECT = "application-architecture"
ASKED = (
    "Construis l'architecture du parcours De l'intention à l'action sur le périmètre "
    "Plateforme LEKA, à la fin il me faut un PDF"
)


def _gemini(said: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(said)}]}}],
            "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 120},
            "modelVersion": "gemini-3.8-flash-001",
        },
    )


class Gemini:
    """Reads the request, chooses the agent it was told to, writes."""

    def __init__(self, choosing: dict[str, Any]) -> None:
        self.choosing = choosing
        self.asked: list[str] = []
        self.offered: list[str] = []
        self.written: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema = body["generationConfig"]["responseJsonSchema"]
        if "restated" in schema["properties"]:
            self.asked.append("reading")
            return _gemini(
                {
                    "mode": "request",
                    "goal": "map_dependencies",
                    "confidence": 0.9,
                    "restated": "Le deck d'architecture du parcours De l'intention à l'action.",
                }
            )
        said = json.loads(body["contents"][0]["parts"][0]["text"])
        if "missing" in schema["properties"]:
            self.asked.append("choosing")
            self.offered = [a["key"] for a in json.loads(said["task"])["agents"]]
            return _gemini(self.choosing)
        self.asked.append("writing")
        task = said["task"]
        self.written.append(task)
        first = task["findings"][0]["id"] if task.get("findings") else None
        return _gemini(
            {
                "answer": "L'Architecte applicatif prépare le deck : PDF et PowerPoint.",
                "points": [{"text": "Le deck est en cours.", "cites": [first] if first else []}],
                "caveats": [],
            }
        )


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Gemini]:
    configured = settings.model_copy(
        update={
            "google_api_key": SecretStr("g-key"),
            "mistral_api_key": None,
            "anthropic_api_key": None,
            "llm_fallbacks": "",
        }
    )
    monkeypatch.setattr(service, "settings", configured)

    def install(choosing: dict[str, Any]) -> Gemini:
        scripted = Gemini(choosing)
        monkeypatch.setattr(
            Gateway,
            "_client",
            lambda self, endpoint, tier: httpx.AsyncClient(transport=httpx.MockTransport(scripted)),
        )
        return scripted

    return install


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """No worker here: what dispatch queues, kept."""
    runs: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        runs.append(run_id)
        return True

    monkeypatch.setattr(dispatch_module, "queue_run", queue)
    return runs


async def _runs(workspace_id: uuid.UUID) -> list[AgentRun]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            return list((await session.scalars(select(AgentRun))).all())


async def test_a_deck_asked_for_starts_the_architect_with_the_request_s_own_words(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    scripted = gemini(
        {
            "agent": ARCHITECT,
            "inputs": {
                "parcours": "De l'intention à l'action",
                "perimetre": "Plateforme LEKA",
                "made_up": "dropped",
            },
            "why": "Un deck d'architecture, en PDF : ce que livre l'Architecte applicatif.",
        }
    )
    _as(identity, acme, "member")
    intention = await _ask(client, ASKED)
    await _analysed(acme, intention)

    assert ARCHITECT in scripted.offered
    [run] = await _runs(acme["acme"])
    assert (run.key, str(run.intention_id), run.requested_by) == (
        ARCHITECT,
        intention["id"],
        acme["member"],
    )
    # Its inputs, the request's own words — exactly its contract's.
    assert run.inputs == {"parcours": "De l'intention à l'action", "perimetre": "Plateforme LEKA"}
    assert started == [run.id]
    # The answer is told the agent is at work, and what it delivers.
    written = next(w for w in scripted.written if "agent_at_work" in w)
    assert written["agent_at_work"]["title"] == "Architecte applicatif"
    assert set(written["agent_at_work"]["deliverables"]) == {"pptx", "pdf"}
    answer = (await _get(client, f"/{intention['id']}/analysis"))["result"]["answer"]
    assert "PDF" in answer["text"]
    # The run on the intention, where its files appear.
    runs = (await client.get("/api/v1/agent-runs", params={"intention_id": intention["id"]})).json()
    assert [r["key"] for r in runs] == [ARCHITECT]
    elsewhere = await client.get("/api/v1/agent-runs", params={"intention_id": str(uuid.uuid4())})
    assert elsewhere.json() == []

    # Once: analysed again, nothing more is started.
    await _analysed(acme, intention)
    assert len(await _runs(acme["acme"])) == 1
    assert started == [run.id]


async def test_an_agent_its_credits_would_stop_midway_is_not_started(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LEKA-439: 30 credits left, a deck has cost 120 here, LEKA's models stop
    # once spent — never started to stop midway.
    await _ready(acme)
    gemini(
        {
            "agent": ARCHITECT,
            "inputs": {"parcours": "De l'intention à l'action", "perimetre": "Plateforme LEKA"},
            "why": "Un deck.",
        }
    )

    async def few(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(enforced=True, state="warning", remaining=30.0)

    async def costly(*args: Any, **kwargs: Any) -> dict[str, float]:
        return {ARCHITECT: 120.0}

    monkeypatch.setattr(metering_credits, "credits_now", few)
    monkeypatch.setattr(feasibility_module, "run_costs", costly)
    _as(identity, acme, "member")
    intention = await _ask(client, ASKED)
    await _analysed(acme, intention)

    assert await _runs(acme["acme"]) == []
    assert started == []


async def test_a_question_starts_no_agent(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    scripted = gemini({"agent": None, "why": "Une question : l'analyse de LEKA répond."})
    _as(identity, acme, "member")
    intention = await _ask(client, "Billing API, c'est à qui de voir ça ?")
    await _analysed(acme, intention)

    assert "choosing" in scripted.asked
    assert await _runs(acme["acme"]) == []
    assert started == []
    assert all("agent_at_work" not in w for w in scripted.written)


def _agents(*keys: str) -> list[Any]:
    found = []
    for key in keys:
        definition = find(key)
        assert definition is not None
        found.append(SimpleNamespace(definition=definition))
    return found


def test_only_an_agent_offered_with_its_required_inputs_is_started() -> None:
    offered = _agents(ARCHITECT)
    # Not offered: nothing.
    assert checked(Dispatched(agent="build-fixer", inputs={}), offered) is None
    # A required input missing: nothing.
    assert checked(Dispatched(agent=ARCHITECT, inputs={"parcours": "X"}), offered) is None
    # Exactly its contract's: unknown ones dropped, a boolean read as one.
    agent, inputs = checked(
        Dispatched(
            agent=ARCHITECT,
            inputs={"parcours": " X ", "perimetre": "Y", "vue_applicative": "oui", "other": "z"},
        ),
        offered,
    ) or (None, {})
    assert agent is offered[0]
    assert inputs == {"parcours": "X", "perimetre": "Y", "vue_applicative": True}
