"""An intention's Décision and Action steps carried by LEKA's agents
(2026-10-14, the product call) — Gemini scripted, no network.

What these protect:
- Its analysis proposes the agents the work needs and the plan, step by
  step: the architect for « … il me faut un PDF », its inputs from the
  request's own words, the PDF asked for — and starts nothing. The answer is
  told what is proposed, never that an agent is at work.
- « Lancer avec ces agents »: only what was proposed, by its asker or who
  may approve; an input missing, an agent that cannot run here, credits
  short — refused, said why, nothing started. Launched: approved then
  executing, its runs queued, only the files asked for drawn.
- Nothing stays « en cours »: once every agent ended, read or swept, the
  intention is verified — or failed, which agent and why, launched again
  with « Relancer », those that delivered kept.
- « Je le fais moi-même »: done by its asker, the plan in hand; its agents
  still launchable after the fact.
- Without a model: the catalogue's own discovery and a plan by goal — a
  migration's steps, the DNS TTL lowered before the switch.
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

from leka.capabilities import AgentRun, Gateway
from leka.capabilities.gateway import service
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from leka.intentions import agents as agents_module
from leka.intentions import feasibility as feasibility_module
from leka.intentions.processing import analyse_pending
from leka.intentions.proposal import plan_by_rules
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import _ready
from tests.test_context_engine import model
from tests.test_intention_analysis_api import API, _analysed, _ask, _get, queued  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name

ARCHITECT = "application-architecture"
ASKED = (
    "Construis l'architecture du parcours De l'intention à l'action sur le périmètre "
    "Plateforme LEKA, à la fin il me faut un PDF"
)
PROPOSED = {
    "agents": [
        {
            "key": ARCHITECT,
            "inputs": {
                "parcours": "De l'intention à l'action",
                "perimetre": "Plateforme LEKA",
                "made_up": "dropped",
            },
            "why": "Le deck d'architecture du parcours, en PDF.",
            "formats": ["pdf"],
        },
        {"key": "made-up-agent", "why": "Not offered: dropped."},
    ],
    "steps": [
        {"title": "Rassembler la documentation du parcours", "detail": "Confluence, le code."},
        {"title": "Dessiner l'architecture", "detail": "Le deck, en PDF.", "agent": ARCHITECT},
        {"title": "Relire et valider", "detail": "Par l'équipe."},
    ],
    "informative": False,
}


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
    """Reads the request, proposes what it was told to, writes."""

    def __init__(self, proposing: dict[str, Any]) -> None:
        self.proposing = proposing
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
        if "steps" in schema["properties"]:
            self.asked.append("proposing")
            self.offered = [a["key"] for a in json.loads(said["task"])["agents"]]
            return _gemini(self.proposing)
        self.asked.append("writing")
        task = said["task"]
        self.written.append(task)
        first = task["findings"][0]["id"] if task.get("findings") else None
        return _gemini(
            {
                "answer": "L'Architecte applicatif peut dessiner ce deck, en PDF.",
                "points": [
                    {"text": "Le parcours est documenté.", "cites": [first] if first else []}
                ],
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

    def install(proposing: dict[str, Any] = PROPOSED) -> Gemini:
        scripted = Gemini(proposing)
        monkeypatch.setattr(
            Gateway,
            "_client",
            lambda self, endpoint, tier: httpx.AsyncClient(transport=httpx.MockTransport(scripted)),
        )
        return scripted

    return install


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """No worker here: what a launch queues, kept."""
    runs: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        runs.append(run_id)
        return True

    monkeypatch.setattr(agents_module, "queue_run", queue)
    return runs


async def _runs(workspace_id: uuid.UUID) -> list[AgentRun]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            return list((await session.scalars(select(AgentRun))).all())


async def _end(workspace_id: uuid.UUID, run_id: uuid.UUID, status: str, **detail: Any) -> None:
    """A worker's end of a run, as it keeps it."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            run.status = status
            run.error = detail.pop("error", None)
            run.detail = {**run.detail, **detail}
            await session.commit()


async def _proposed(client: AsyncClient, acme: dict[str, uuid.UUID]) -> dict[str, Any]:
    intention = await _ask(client, ASKED)
    await _analysed(acme, intention)
    return intention


LAUNCH = {
    "agents": [
        {
            "key": ARCHITECT,
            "inputs": {"parcours": "De l'intention à l'action", "perimetre": "Plateforme LEKA"},
            "formats": ["pdf"],
        }
    ]
}


async def test_its_analysis_proposes_the_agents_and_the_plan_and_starts_nothing(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    scripted = gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)

    assert ARCHITECT in scripted.offered
    # Nothing started: a person launches it (2026-10-14).
    assert await _runs(acme["acme"]) == []
    assert started == []
    seen = await _get(client, f"/{intention['id']}")
    assert seen["status"] == "awaiting_decision"
    assert {"launch_agents", "by_hand"} <= set(seen["journey"]["controls"])
    proposal = (await _get(client, f"/{intention['id']}/analysis"))["result"]["proposal"]
    [agent] = proposal["agents"]
    assert (agent["key"], agent["title"], agent["available"]) == (
        ARCHITECT,
        "Architecte applicatif",
        True,
    )
    # Its inputs, the request's own words — exactly its contract's.
    assert agent["inputs"] == {
        "parcours": "De l'intention à l'action",
        "perimetre": "Plateforme LEKA",
    }
    assert (agent["missing"], agent["asked"]) == ([], ["pdf"])
    assert agent["deliverables"] == ["report", "pptx", "pdf"]
    assert [s["title"] for s in proposal["steps"]][1] == "Dessiner l'architecture"
    assert proposal["steps"][1]["agent"] == ARCHITECT
    assert (proposal["informative"], proposal["by"]) == (False, "model")
    # The answer is told what is proposed — never that it is at work.
    written = next(w for w in scripted.written if "proposed" in w)
    assert written["proposed"]["agents"][0]["title"] == "Architecte applicatif"


async def test_launched_by_a_person_only_what_was_proposed_and_the_files_asked(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    url = f"{API}/{intention['id']}/agents"

    # Not proposed: refused, nothing started.
    other = await client.post(url, json={"agents": [{"key": "code-review"}]})
    assert (other.status_code, other.json()["error"]["code"]) == (422, "agent_not_proposed")
    # An input missing: refused, said which.
    lacking = await client.post(
        url, json={"agents": [{"key": ARCHITECT, "inputs": {"parcours": "X"}}]}
    )
    assert (lacking.status_code, lacking.json()["error"]["code"]) == (422, "agent_inputs_missing")
    assert [d["field"] for d in lacking.json()["error"]["details"]] == [
        f"agents.{ARCHITECT}.inputs.perimetre"
    ]
    assert await _runs(acme["acme"]) == []

    launched = await client.post(url, json=LAUNCH)
    assert launched.status_code == 200, launched.text
    said = launched.json()
    assert said["status"] == "executing"
    assert (said["journey"]["state"], said["journey"]["path"]) == ("action_running", "agents")
    [run] = await _runs(acme["acme"])
    assert (run.key, str(run.intention_id), run.requested_by) == (
        ARCHITECT,
        intention["id"],
        acme["member"],
    )
    # Only the PDF asked for will be drawn.
    assert run.detail["formats"] == ["pdf"]
    assert started == [run.id]
    names = [
        e["name"] for e in await _get(client, f"/{intention['id']}/history") if e["kind"] == "moved"
    ]
    assert names[-2:] == ["approved", "execution_started"]
    # Launched once: launching again is refused by its state.
    again = await client.post(url, json=LAUNCH)
    assert again.status_code == 409


async def test_credits_short_or_an_agent_that_cannot_run_starts_nothing(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)

    async def few(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(enforced=True, state="warning", remaining=30.0)

    async def costly(*args: Any, **kwargs: Any) -> dict[str, float]:
        return {ARCHITECT: 120.0}

    monkeypatch.setattr(feasibility_module, "credits_left", few)
    monkeypatch.setattr(feasibility_module, "run_costs", costly)
    short = await client.post(f"{API}/{intention['id']}/agents", json=LAUNCH)
    assert (short.status_code, short.json()["error"]["code"]) == (422, "credits_short")
    assert await _runs(acme["acme"]) == []
    assert (await _get(client, f"/{intention['id']}"))["status"] == "awaiting_decision"


async def test_once_its_agents_ended_it_is_verified_or_failed_then_launched_again(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    await client.post(f"{API}/{intention['id']}/agents", json=LAUNCH)
    [run] = await _runs(acme["acme"])

    # Still running: executing, nothing settled.
    assert (await _get(client, f"/{intention['id']}"))["status"] == "executing"
    # It timed out: failed — read, it says which agent and why.
    await _end(acme["acme"], run.id, "failed", error="timeout")
    failed = await _get(client, f"/{intention['id']}")
    assert failed["status"] == "failed"
    assert (failed["journey"]["state"], failed["journey"]["reason"]) == (
        "action_failed",
        "agent_failed",
    )
    assert failed["journey"]["technical"] == "timeout"
    assert "retry_agents" in failed["journey"]["controls"]

    # « Relancer »: launched again with what it was given.
    retried = await client.post(f"{API}/{intention['id']}/agents/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "executing"
    runs = await _runs(acme["acme"])
    [again] = [r for r in runs if r.id != run.id]
    assert (again.key, again.inputs, again.detail["formats"]) == (ARCHITECT, run.inputs, ["pdf"])
    assert started == [run.id, again.id]

    # Delivered — settled by the sweep, nobody reading it: verified.
    await _end(acme["acme"], again.id, "succeeded", deliverables=[{"format": "pdf"}])
    assert (await analyse_pending())["settled"] == 1
    done = await _get(client, f"/{intention['id']}")
    assert done["status"] == "completed"
    assert (done["journey"]["state"], done["journey"]["path"]) == ("done", "agents")
    assert (done["journey"]["step"]["at"], done["journey"]["step"]["done"]) == ("action", True)
    moved = [e for e in await _get(client, f"/{intention['id']}/history") if e["kind"] == "moved"]
    assert moved[-1]["detail"]["delivered"] == [
        {"agent": ARCHITECT, "run_id": str(again.id), "files": ["pdf"]}
    ]


async def test_done_by_hand_the_plan_in_hand_its_agents_still_there(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)

    mine = await client.post(f"{API}/{intention['id']}/by-hand")
    assert mine.status_code == 200, mine.text
    said = mine.json()
    assert said["status"] == "completed"
    assert (said["journey"]["state"], said["journey"]["reason"], said["journey"]["path"]) == (
        "done",
        "by_hand",
        "self",
    )
    assert said["journey"]["step"]["last"] == 4
    assert await _runs(acme["acme"]) == []
    # Taken further after all: its agents launched after the fact.
    later = await client.post(f"{API}/{intention['id']}/agents", json=LAUNCH)
    assert later.status_code == 200, later.text
    assert later.json()["status"] == "executing"


async def test_only_its_asker_or_who_may_approve_decides(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "admin")
    intention = await _proposed(client, acme)
    _as(identity, acme, "member")
    refused = await client.post(f"{API}/{intention['id']}/by-hand")
    assert refused.status_code == 403


def test_without_a_model_a_plan_by_goal() -> None:
    steps = plan_by_rules("plan_migration", "fr", ["infrastructure-analysis"])
    titles = [s.title for s in steps]
    assert titles[0] == "Inventorier ce qui migre"
    assert "Basculer le trafic" in titles
    assert any("TTL" in s.detail for s in steps)
    assert steps[1].agent == "infrastructure-analysis"
    english = plan_by_rules("explain_cause", "en", [])
    assert english[0].title == "Gather what changed"
    assert all(s.agent is None for s in english)
