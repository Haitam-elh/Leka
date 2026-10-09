"""Intentions read and answered with a language model (LEKA-394): the
gateway consumed by an Intention flow — the reading — and by a Capability
flow — the synthesis — end to end, Gemini scripted.

Acme's company model (test_knowledge_graph): Billing API, owned by
Payments; Checkout depends on it.

What these protect:
- Words the rules cannot read — no goal said — are read by the model: the
  goal settled, the intention analysed instead of stopped for a question;
  who read it said, what was asked in a sentence; the call kept.
- A request to act stays the rules': a model calling it a question changes
  nothing — a person still decides.
- The analysis answered in words: the synthesis runs after the rules,
  chosen by what it needs of a model, writes from what they found — every
  point citing what the result holds, a citation it does not hold dropped —
  and the intention's summary is that answer. An answer resting on nothing
  is not kept, and said.
- Without a model, the rules alone, as before: test_intention_analysis_api.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from leka.capabilities import Gateway, ModelCall
from leka.capabilities.gateway import service
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from leka.intentions.models import IntentionDecision, IntentionPlan
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_analysis_api import _analysed, _ask, _get, queued  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name


def _gemini(said: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(said)}]}}],
            "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 120},
            "modelVersion": "gemini-3.8-flash-001",
        },
    )


Writer = Callable[[dict[str, Any]], dict[str, Any]]


def _cite_the_first(material: dict[str, Any]) -> dict[str, Any]:
    first = material["findings"][0]["id"]
    return {
        "answer": "Billing API appartient à Payments.",
        "points": [
            {"text": "Payments en est responsable.", "cites": [first, "made-up"]},
            {"text": "Un point sans source.", "cites": ["made-up"]},
        ],
        "caveats": [],
    }


class Gemini:
    """Reads like a model asked to read, writes like one asked to write."""

    def __init__(self, reading: dict[str, Any], writing: Writer = _cite_the_first) -> None:
        self.reading = reading
        self.writing = writing
        self.asked: list[str] = []
        self.contexts: list[list[dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema = body["generationConfig"]["responseJsonSchema"]
        if "restated" in schema["properties"]:
            self.asked.append("reading")
            return _gemini(self.reading)
        self.asked.append("writing")
        # The runtime says the task and its LEKA context apart (LEKA-429).
        said = json.loads(body["contents"][0]["parts"][0]["text"])
        self.contexts.append(said.get("context", []))
        return _gemini(self.writing(said["task"]))


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Gemini]:
    """LEKA holds a Gemini key; what Gemini says, scripted."""
    configured = settings.model_copy(
        update={
            "google_api_key": SecretStr("g-key"),
            "mistral_api_key": None,
            "anthropic_api_key": None,
            "llm_fallbacks": "",
        }
    )
    monkeypatch.setattr(service, "settings", configured)

    def install(reading: dict[str, Any], writing: Writer = _cite_the_first) -> Gemini:
        scripted = Gemini(reading, writing)
        monkeypatch.setattr(
            Gateway,
            "_client",
            lambda self, endpoint, tier: httpx.AsyncClient(transport=httpx.MockTransport(scripted)),
        )
        return scripted

    return install


async def _calls(workspace_id: uuid.UUID) -> list[ModelCall]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            return list((await session.scalars(select(ModelCall).order_by(ModelCall.at))).all())


async def test_words_the_rules_cannot_read_are_read_by_the_model_and_answered(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
) -> None:
    scripted = gemini(
        {
            "mode": "question",
            "goal": "find_owner",
            "confidence": 0.85,
            "restated": "Qui s'occupe de Billing API ?",
        }
    )
    _as(identity, acme, "member")
    intention = await _ask(client, "Billing API, c'est à qui de voir ça ?")
    understood = intention["understanding"]
    assert understood["goal"]["code"] == "find_owner"
    assert understood["read_by"]["method"] == "model"
    assert understood["read_by"]["version"] == "gemini-3.8-flash-001"
    assert understood["restated"] == "Qui s'occupe de Billing API ?"
    assert intention["status"] == "analysing"

    await _analysed(acme, intention)
    analysis = await _get(client, f"/{intention['id']}/analysis")
    steps = {s["name"]: s["status"] for s in analysis["steps"]}
    assert steps["synthesis"] == "succeeded"
    answer = analysis["result"]["answer"]
    assert answer["text"] == "Billing API appartient à Payments."
    assert (answer["provider"], answer["model"]) == ("google", "gemini-3.8-flash")
    # Only what the result holds is cited; a point citing nothing it holds goes.
    assert [p["text"] for p in answer["points"]] == ["Payments en est responsable."]
    assert answer["points"][0]["cites"] == [analysis["result"]["findings"][0]["id"]]
    seen = await _get(client, f"/{intention['id']}")
    assert seen["summary"] == "Billing API appartient à Payments."

    assert scripted.asked == ["reading", "writing"]
    calls = await _calls(acme["acme"])
    assert [(c.purpose, c.status) for c in calls] == [
        ("intention.understanding", "ok"),
        ("capability.synthesis", "ok"),
    ]
    assert calls[1].ref == f"intention:{intention['id']}"


async def test_a_request_to_act_stays_the_rules(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
) -> None:
    gemini({"mode": "question", "goal": "investigate", "confidence": 0.95, "restated": "x"})
    _as(identity, acme, "member")
    intention = await _ask(client, "Redémarre Billing API en production")
    understood = intention["understanding"]
    assert (understood["mode"], understood["goal"]["code"]) == ("request", "act")
    assert [a["code"] for a in understood["actions"]] == ["restart"]
    assert understood["read_by"]["method"] == "model"


async def test_an_answer_resting_on_nothing_is_not_kept(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
) -> None:
    gemini(
        {"mode": "question", "goal": "find_owner", "confidence": 0.9, "restated": "x"},
        lambda material: {
            "answer": "Sans doute l'équipe Infra.",
            "points": [{"text": "L'équipe Infra.", "cites": ["made-up"]}],
            "caveats": [],
        },
    )
    _as(identity, acme, "member")
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    await _analysed(acme, intention)
    analysis = await _get(client, f"/{intention['id']}/analysis")
    synthesis = next(s for s in analysis["steps"] if s["name"] == "synthesis")
    assert (synthesis["status"], synthesis["error"]) == ("failed", "ungrounded")
    assert analysis["result"]["answer"] is None
    # The rules' analysis stands, whole.
    assert analysis["status"] == "complete"


async def test_a_model_saying_to_act_sets_nothing_in_motion(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
) -> None:
    """LEKA-429: an LLM's output never triggers a sensitive action. The model
    reads a question as a request to act, then writes « restart it in
    production »: the question stays a question — no action, no decision,
    no plan — answered, and only said."""
    gemini(
        {
            "mode": "request",
            "goal": "act",
            "confidence": 0.99,
            "restated": "Redémarrer Billing API",
        },
        lambda material: {
            "answer": "Il faut redémarrer Billing API en production.",
            "points": [
                {"text": "Redémarrez-le maintenant.", "cites": [material["findings"][0]["id"]]}
            ],
            "caveats": [],
        },
    )
    _as(identity, acme, "member")
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    understood = intention["understanding"]
    assert (understood["mode"], understood["goal"]["code"], understood["actions"]) == (
        "question",
        "find_owner",
        [],
    )
    await _analysed(acme, intention)
    seen = await _get(client, f"/{intention['id']}")
    # A question answered: completed, nobody asked to decide anything.
    assert seen["status"] == "completed"
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            ident = uuid.UUID(intention["id"])
            decisions = await session.scalars(
                select(IntentionDecision).where(IntentionDecision.intention_id == ident)
            )
            plans = await session.scalars(
                select(IntentionPlan).where(IntentionPlan.intention_id == ident)
            )
            assert (list(decisions), list(plans)) == ([], [])
