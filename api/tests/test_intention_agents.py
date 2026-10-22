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
- Kept to some sources (« l'Architecte sur Confluence seul »): the run
  says which, and sees nothing that came from no other.
- Without a model: the catalogue's own discovery and a plan by goal — a
  migration's steps, the DNS TTL lowered before the switch.
- An agent the person names by its « /mot » (the new home's chips) is
  proposed whatever the model chose — still launched by a person only.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text

from leka.capabilities import AgentRun, Gateway
from leka.capabilities.definition import Kind
from leka.capabilities.gateway import service
from leka.capabilities.registry import agents as agent_definitions
from leka.capabilities.runs import outside_sources
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from leka.intentions import agents as agents_module
from leka.intentions import feasibility as feasibility_module
from leka.intentions.processing import analyse_pending
from leka.intentions.proposal import asked_words, named, plainly_asked, plan_by_rules
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

    def __init__(self, proposing: dict[str, Any], corrected: dict[str, Any] | None = None) -> None:
        self.proposing = proposing
        # What it answers once told why its first answer is not used.
        self.corrected = corrected
        self.told: list[str] = []
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
            if len(body["contents"]) > 1:
                self.told.append(body["contents"][-1]["parts"][0]["text"])
                if self.corrected is not None:
                    return _gemini(self.corrected)
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

    def install(
        proposing: dict[str, Any] = PROPOSED, corrected: dict[str, Any] | None = None
    ) -> Gemini:
        scripted = Gemini(proposing, corrected)
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


async def test_a_question_is_never_proposed_what_proposes_a_change(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    # 2026-10-19: « pourquoi … échouent ? » was proposed the build fixer,
    # and not the debugging agent.
    await _ready(acme)
    scripted = gemini(
        {
            "agents": [{"key": "build-fixer"}, {"key": "debug-assistant"}],
            "steps": [{"title": "Diagnostiquer", "agent": "debug-assistant"}],
            "informative": False,
        }
    )
    _as(identity, acme, "member")
    intention = await _ask(client, "Pourquoi les déploiements de Billing API échouent-ils ?")
    await _analysed(acme, intention)

    assert "build-fixer" not in scripted.offered
    assert "debug-assistant" in scripted.offered
    proposal = (await _get(client, f"/{intention['id']}/analysis"))["result"]["proposal"]
    assert [a["key"] for a in proposal["agents"]] == ["debug-assistant"]


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


async def test_kept_to_some_sources_it_sees_nothing_that_came_from_no_other(
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
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            entity, source = (
                await session.execute(
                    # This workspace's: raw SQL is not scoped, and another
                    # test's entity made it fail one run in two (2026-10-21).
                    text(
                        "SELECT id, provenance -> 'sources' -> 0 ->> 'source_id' FROM entities "
                        "WHERE workspace_id = :w "
                        "AND jsonb_array_length(provenance -> 'sources') > 0 ORDER BY id LIMIT 1"
                    ),
                    {"w": acme["acme"]},
                )
            ).one()
            kept = await outside_sources(session, acme["acme"], [source])
            elsewhere = await outside_sources(session, acme["acme"], [str(uuid.uuid4())])
    assert entity not in kept
    assert entity in elsewhere

    launched = await client.post(
        f"{API}/{intention['id']}/agents",
        json={"agents": [{**LAUNCH["agents"][0], "sources": [source]}]},
    )
    assert launched.status_code == 200, launched.text
    [run] = await _runs(acme["acme"])
    assert run.detail["sources"] == [source]


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


async def test_an_agent_named_by_its_slash_word_is_proposed_whatever_the_model_chose(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini(
        {"agents": [], "steps": [{"title": "Lire la réponse", "detail": ""}], "informative": True}
    )
    _as(identity, acme, "member")
    intention = await _ask(client, f"/architecte {ASKED}")
    await _analysed(acme, intention)

    proposal = (await _get(client, f"/{intention['id']}/analysis"))["result"]["proposal"]
    [agent] = proposal["agents"]
    assert (agent["key"], agent["asked"]) == (ARCHITECT, ["pdf"])
    # Named, it is work to do — not a question answered.
    assert proposal["informative"] is False
    # Proposed, never started: a person launches it.
    assert started == []


def test_a_slash_word_names_one_agent_or_none() -> None:
    def entry(key: str, title: str) -> SimpleNamespace:
        return SimpleNamespace(definition=SimpleNamespace(key=key, title=title))

    entries = [
        entry(ARCHITECT, "Architecte applicatif"),
        entry("code-review", "Revue de code"),
        entry("security-review", "Revue de sécurité"),
    ]
    assert named("/architecte construis le parcours", entries) == ARCHITECT
    assert named("  /code-review ce diff", entries) == "code-review"
    assert named("/revue-de-securite du module", entries) == "security-review"
    # A word two agents share names neither; no slash, no name.
    assert named("/revue du module", entries) is None
    assert named("architecte du parcours", entries) is None


async def test_one_launch_one_set_of_runs_a_double_click_or_a_slow_network_alike(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    """LEKA-465: one submission starts one run — sent twice at once, or again
    while it runs, refused, said why; the state kept on the server."""
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    url = f"{API}/{intention['id']}/agents"
    first, second = await asyncio.gather(
        client.post(url, json=LAUNCH), client.post(url, json=LAUNCH)
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes[0] == 200 and codes[1] in (409, 422), (first.text, second.text)
    again = await client.post(url, json=LAUNCH)
    assert again.status_code in (409, 422), again.text
    assert len(await _runs(acme["acme"])) == 1
    # Read again — a refresh, another tab: still at work, its run there.
    read = await _get(client, f"/{intention['id']}")
    assert (read["status"], read["journey"]["state"]) == ("executing", "action_running")


async def test_an_agent_named_another_way_by_the_model_is_the_catalogue_s_own(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    """2026-10-21: Mistral named the agents its own way — by title, with
    underscores — and every one was dropped: nothing was proposed."""
    await _ready(acme)
    gemini(
        {
            **PROPOSED,
            "agents": [
                {
                    "key": "Architecte applicatif",
                    "inputs": {
                        "parcours": "De l'intention à l'action",
                        "perimetre": "Plateforme LEKA",
                    },
                    "formats": ["pdf"],
                }
            ],
            "steps": [
                {
                    "title": "Dessiner l'architecture",
                    "detail": "",
                    "agent": "application_architecture",
                }
            ],
        }
    )
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    proposal = (await _get(client, f"/{intention['id']}/analysis"))["result"]["proposal"]
    [agent] = proposal["agents"]
    assert agent["key"] == ARCHITECT
    assert proposal["steps"][0]["agent"] == ARCHITECT
    assert proposal["by"] == "model"


async def test_work_to_do_and_no_agent_leka_knows_the_catalogue_proposes_one(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    """Agents LEKA does not have, for work to do: never nothing proposed —
    the catalogue's own discovery, a plan by goal."""
    await _ready(acme)
    gemini({"agents": [{"key": "architecture-bot"}], "steps": [], "informative": False})
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    proposal = (await _get(client, f"/{intention['id']}/analysis"))["result"]["proposal"]
    assert proposal["by"] == "rules"
    assert proposal["agents"], proposal
    assert started == []


async def test_a_request_answered_with_no_agent_at_all_gets_the_catalogue_s(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    """2026-10-21: « Propose-moi un meilleur design … » — a request that
    changes nothing itself — answered by Mistral with no agent at all: the
    catalogue's own are proposed, never « aucun agent ne fait ce travail »."""
    await _ready(acme)
    gemini({"agents": [], "steps": [], "informative": False})
    _as(identity, acme, "member")
    intention = await _proposed(client, acme)
    proposal = (await _get(client, f"/{intention['id']}/analysis"))["result"]["proposal"]
    assert (proposal["by"], bool(proposal["agents"])) == ("rules", True)
    assert proposal["informative"] is False
    assert len(proposal["agents"]) <= 3


DESIGN = "Propose-moi un meilleur design pour la page mon environnement de Haitam-elh/Leka"


def test_the_words_plainly_name_the_design_review_not_the_alphabet() -> None:
    """2026-10-21: words capped at three made most agents tie, and the
    alphabet chose; a word of an agent's name now counts most."""
    found = {d.key: d for d in agent_definitions(settings.agents_dir) if d.kind is Kind.AGENT}
    entries = {key: SimpleNamespace(definition=d) for key, d in found.items()}
    plain, scores = plainly_asked(entries, asked_words(DESIGN))
    assert plain[0] == "design-review"
    assert scores["documentation-assistant"] == 0
    # A name is what a request is about, never the work it asks: « payment-api »
    # asks nothing of the API review; « l'API » does (2026-10-22).
    for about in (
        "Pourquoi payment-api est lente depuis hier ?",
        "Billing API, c'est à qui de voir ça ?",
        "Redémarre Billing API",
    ):
        plain_here, _ = plainly_asked(entries, asked_words(about))
        assert "api-design-review" not in plain_here, about
    asked, _ = plainly_asked(entries, asked_words("Fais une revue de l'API de acme/api"))
    assert asked[0] == "api-design-review"


async def test_a_model_told_why_its_choice_does_not_fit_chooses_again_itself(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    """2026-10-21: asked a better design, a model chose the documentation
    assistant alone. Told why that does not fit — what the request asks,
    what the design review delivers — it chooses again, itself: the model's
    choice, never a replacement LEKA makes."""
    await _ready(acme)
    scripted = gemini(
        {
            "agents": [{"key": "documentation-assistant", "why": "Documenter la page."}],
            "steps": [{"title": "Documenter", "agent": "documentation-assistant"}],
            "informative": False,
        },
        corrected={
            "agents": [
                {"key": "design-review", "why": "La page redessinée, avant et après."},
                {"key": "code-change", "why": "Le changement de code qui la met en œuvre."},
            ],
            "steps": [
                {"title": "Redessiner la page", "detail": "", "agent": "design-review"},
                {"title": "Écrire le changement", "detail": "", "agent": "code-change"},
            ],
            "informative": False,
        },
    )
    _as(identity, acme, "member")
    intention = await _ask(client, DESIGN)
    await _analysed(acme, intention)
    # Shown to the model the most relevant first.
    assert scripted.offered[0] == "design-review"
    [told] = scripted.told
    assert "do not do what the request asks" in told and "design-review" in told
    proposal = (await _get(client, f"/{intention['id']}/analysis"))["result"]["proposal"]
    assert [a["key"] for a in proposal["agents"]] == ["design-review", "code-change"]
    assert proposal["steps"][0]["agent"] == "design-review"
    # The model's choice, said whose.
    assert (proposal["by"], proposal["model"]) == ("model", "gemini-3.8-flash")


async def test_a_model_that_never_chooses_what_the_work_needs_leaves_it_to_the_catalogue(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    """Told, and still wrong, and no other model to ask: the catalogue's
    own, the design review first — never the documentation assistant."""
    await _ready(acme)
    gemini(
        {
            "agents": [{"key": "documentation-assistant"}],
            "steps": [],
            "informative": False,
        }
    )
    _as(identity, acme, "member")
    intention = await _ask(client, DESIGN)
    await _analysed(acme, intention)
    proposal = (await _get(client, f"/{intention['id']}/analysis"))["result"]["proposal"]
    keys = [a["key"] for a in proposal["agents"]]
    assert (proposal["by"], keys[0]) == ("rules", "design-review")
    assert "documentation-assistant" not in keys
