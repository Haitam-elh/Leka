"""LEKA's analyst: an intention answered by a language model that reads
what it needs through LEKA's own tools — Gemini scripted, no network.

Acme's company model (test_knowledge_graph): Billing API, owned by
Payments; Checkout depends on it.

What these protect:
- The model is told what LEKA is and given LEKA's tools — every one to
  read, none to act; what a tool returns goes back to it; its answer cites
  what the tools returned, and that becomes the analysis's evidence (the
  Preuves tab).
- A citation of nothing it read or was given is dropped; an answer resting
  on nothing, when there was something, is not kept: LEKA says what its
  rules found instead — the synthesis as it was (writing.py).
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import Gateway, SkillRuntime, find_skill
from leka.capabilities.gateway import service
from leka.capabilities.skills import LEKA
from leka.core.config import settings
from leka.intelligence import LIBRARY
from leka.intentions.analysis import Asked
from leka.intentions.analyst import ANALYST_SKILLS, PLATFORM, Reading, tools
from leka.intentions.skills import READS
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_analysis_api import _analysed, _ask, _get, queued  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name

READING = {
    "mode": "question",
    "goal": "find_owner",
    "confidence": 0.85,
    "restated": "Qui s'occupe de Billing API ?",
}


def _said(parts: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"role": "model", "parts": parts}}],
            "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 80},
            "modelVersion": "gemini-3.8-flash-001",
        },
    )


Answering = Callable[[str], dict[str, Any]]


def _citing(found: str) -> dict[str, Any]:
    return {
        "answer": "Billing API est tenu par l'équipe Payments.",
        "points": [
            {"text": "Payments répond de Billing API.", "cites": [found, "made-up"]},
            {"text": "Un point sans source.", "cites": ["made-up"]},
        ],
        "caveats": [],
    }


def _citing_nothing(_found: str) -> dict[str, Any]:
    return {"answer": "Payments, sans doute.", "points": [{"text": "…", "cites": ["x"]}]}


def _from_the_rules(task: dict[str, Any]) -> dict[str, Any]:
    first = task["findings"][0]["id"]
    return {
        "answer": "D'après LEKA : Payments.",
        "points": [{"text": "Payments.", "cites": [first]}],
    }


class Analyst:
    """Gemini, asked to read, reads; asked the question with tools, looks
    the thing up first, then answers as it is told to; asked without tools
    — the synthesis of what the rules found — says it."""

    def __init__(self, answering: Answering) -> None:
        self.answering = answering
        self.asked: list[str] = []
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        schema = body["generationConfig"]["responseJsonSchema"]
        if "restated" in schema["properties"]:
            self.asked.append("reading")
            return _said([{"text": json.dumps(READING)}])
        task = json.loads(body["contents"][0]["parts"][0]["text"])["task"]
        if "tools" not in body:
            self.asked.append("writing")
            return _said([{"text": json.dumps(_from_the_rules(task))}])
        back = [
            part["functionResponse"]
            for content in body["contents"]
            for part in content["parts"]
            if "functionResponse" in part
        ]
        if not back:
            self.asked.append("looking")
            [about] = task["about"]
            return _said([{"functionCall": {"name": "describe", "args": {"id": about["id"]}}}])
        self.asked.append("answering")
        read = json.loads(back[-1]["response"]["result"])
        return _said([{"text": json.dumps(self.answering(read["id"]))}])


@pytest.fixture
def analyst(monkeypatch: pytest.MonkeyPatch) -> Callable[[Answering], Analyst]:
    configured = settings.model_copy(
        update={
            "google_api_key": SecretStr("g-key"),
            "mistral_api_key": None,
            "anthropic_api_key": None,
            "llm_fallbacks": "",
        }
    )
    monkeypatch.setattr(service, "settings", configured)

    def install(answering: Answering) -> Analyst:
        scripted = Analyst(answering)
        monkeypatch.setattr(
            Gateway,
            "_client",
            lambda self, endpoint, tier: httpx.AsyncClient(transport=httpx.MockTransport(scripted)),
        )
        return scripted

    return install


async def test_the_analyst_reads_through_leka_s_tools_and_its_answer_rests_on_what_it_read(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    analyst: Callable[[Answering], Analyst],
) -> None:
    scripted = analyst(_citing)
    _as(identity, acme, "member")
    intention = await _ask(client, "Billing API, c'est à qui de voir ça ?")
    await _analysed(acme, intention)

    assert scripted.asked == ["reading", "looking", "answering"]
    looking = scripted.bodies[1]
    # Told what LEKA is; given its tools — read only — to look for itself.
    assert looking["systemInstruction"]["parts"][0]["text"].startswith(PLATFORM[:40])
    names = {f["name"] for t in looking["tools"] for f in t["functionDeclarations"]}
    # LEKA's reads, then its skill library (LEKA-401).
    assert names == set(ANALYST_SKILLS)
    assert {"find", "describe", "delivery-metrics", "blast-radius"} <= names
    analysis = await _get(client, f"/{intention['id']}/analysis")
    assert {s["name"]: s["status"] for s in analysis["steps"]}["synthesis"] == "succeeded"
    result = analysis["result"]
    answer = result["answer"]
    assert answer["text"] == "Billing API est tenu par l'équipe Payments."
    # What it cites that it never read is dropped, and the point citing only that.
    [point] = answer["points"]
    [cited] = point["cites"]
    assert cited.startswith("entity:")
    # What it read and cites is the analysis's evidence: the Preuves tab.
    held = {e["id"]: e for e in result["evidence"]}
    assert held[cited]["label"] == "Billing API"
    assert held[cited]["kind"] == "entity"
    assert result["status"] == "complete"
    assert (await _get(client, f"/{intention['id']}"))["summary"] == answer["text"]
    # Every read through the skill runtime (LEKA-396): checked, for the person
    # who asked, kept about the intention.
    reads = await client.get("/api/v1/skills/runs", params={"ref": f"intention:{intention['id']}"})
    assert [(r["key"], r["status"], r["caller"]) for r in reads.json()] == [
        ("describe", "succeeded", "analyst"),
        ("sources", "succeeded", "analyst"),
    ]
    assert {r["run_by"] for r in reads.json()} == {str(acme["member"])}


async def test_an_answer_resting_on_nothing_it_read_is_not_kept(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    analyst: Callable[[Answering], Analyst],
) -> None:
    scripted = analyst(_citing_nothing)
    _as(identity, acme, "member")
    intention = await _ask(client, "Billing API, c'est à qui de voir ça ?")
    await _analysed(acme, intention)

    # Not kept: what the rules found is said instead.
    assert scripted.asked == ["reading", "looking", "answering", "writing"]
    analysis = await _get(client, f"/{intention['id']}/analysis")
    assert analysis["result"]["answer"]["text"] == "D'après LEKA : Payments."


def test_every_tool_the_analyst_is_given_is_one_of_leka_s_reads() -> None:
    asked = Asked(
        id=uuid.uuid4(),
        text="Quoi de neuf ?",
        mode="question",
        kind="change",
        goal="find_change",
    )
    skills = SkillRuntime(
        cast(AsyncSession, None), uuid.uuid4(), permissions=LEKA, by=None, caller="analyst"
    )
    given = tools(skills, asked, Reading())
    assert [tool.name for tool in given] == [*READS, *(s.key for s in LIBRARY)]
    assert {tool.effect for tool in given} == {"read"}
    assert {find_skill(t.name).effect for t in given} == {"read"}  # type: ignore[union-attr]
