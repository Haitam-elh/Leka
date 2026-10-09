"""The LLM runtime (LEKA-429), against the database — Gemini scripted, no
network.

What these protect:
- A task is done through the gateway with its LEKA context — each item
  with its id — its instructions and LEKA's own rules first; its structured
  answer checked against its shape AND its own check before it is handed
  on; the execution kept: purpose, ref, status, provider, model, the version
  that answered, its calls, tokens, cost, latency, the context it was given
  — and each call says which execution it was part of.
- How it ended is a status, never an exception to guess at: invalid (a
  shape or a check that never held, asked again first), no_model (none can
  do what is needed), timed_out (its budget spent, tools or not), failed
  (every model refused; tools in rounds without end).
- A model reads, never acts: a tool that would change something cannot be
  given to it; the tools it may call are called and their answers given
  back; a caller writing its own conversation (an agent's) keeps it.
- A context the Context Engine assembled is given as it ranked it, each
  element in its line for a model, cut to size — what was left out said.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field
from sqlalchemy import select

from leka.capabilities import (
    ContextItem,
    ContextPack,
    Gateway,
    LLMRun,
    LLMRuntime,
    Message,
    ModelCall,
    Needs,
    RuntimeTool,
    SensitiveToolError,
    Task,
    Tier,
    cites,
)
from leka.capabilities.llm import GUARDRAILS
from leka.db import session_factory, system_scope, workspace_scope
from leka.platform import Workspace

pytestmark = pytest.mark.integration

KEYS: dict[str, str | None] = {"google": "g-key", "mistral": None, "anthropic": None}
GOOGLE = "generativelanguage.googleapis.com"


class Owner(BaseModel):
    owner: str
    cites: list[str] = Field(default_factory=list)


def gemini(said: dict[str, Any] | str, *, version: str = "gemini-3.8-flash-001") -> httpx.Response:
    text = said if isinstance(said, str) else json.dumps(said)
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 500, "candidatesTokenCount": 40},
            "modelVersion": version,
        },
    )


def calling(name: str, args: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"functionCall": {"name": name, "args": args, "id": "t1"}}],
                    }
                }
            ],
            "usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 10},
            "modelVersion": "gemini-3.8-flash-001",
        },
    )


Answer = httpx.Response | Callable[[httpx.Request], Any]


class Script:
    def __init__(self, *answers: Answer) -> None:
        self.answers = list(answers)
        self.asked: list[dict[str, Any]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(json.loads(request.content))
        answer = self.answers.pop(0)
        if not callable(answer):
            return answer
        said = answer(request)
        found = await said if inspect.isawaitable(said) else said
        assert isinstance(found, httpx.Response)
        return found


@pytest.fixture
async def workspace() -> AsyncIterator[uuid.UUID]:
    with system_scope():
        async with session_factory() as session:
            found = Workspace(name="Runtime", slug=f"runtime-{uuid.uuid4().hex[:10]}")
            session.add(found)
            await session.commit()
            workspace_id = found.id
    yield workspace_id
    with system_scope():
        async with session_factory() as session:
            leftover = await session.get(Workspace, workspace_id)
            if leftover is not None:
                await session.delete(leftover)
            await session.commit()


async def _run(
    workspace_id: uuid.UUID, script: Script, task: Task, *, keys: dict[str, str | None] = KEYS
) -> Any:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            gateway = Gateway(
                session,
                workspace_id,
                transport=httpx.MockTransport(script),
                keys=keys,
                default=("google", "gemini-3.8-flash"),
                fallbacks=[],
                retries=1,
                sleep=lambda _: asyncio.sleep(0),
            )
            done = await LLMRuntime(session, workspace_id, gateway=gateway).run(task)
            await session.commit()
            return done


async def _kept(workspace_id: uuid.UUID) -> tuple[list[LLMRun], list[ModelCall]]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            runs = (await session.scalars(select(LLMRun).order_by(LLMRun.started_at))).all()
            calls = (await session.scalars(select(ModelCall).order_by(ModelCall.at))).all()
            return list(runs), list(calls)


CONTEXT = ContextPack.of(
    [
        ContextItem("entity:payment-api", "service", "payment-api, a service", ("github",)),
        ContextItem("relationship:owned", "owned_by", "payment-api is owned by Payments"),
    ],
    ref="context:test:v1",
)


def grounded(value: Any, context: ContextPack) -> list[str]:
    return [] if cites(value) and cites(value) <= context.ids else ["cites what it was not given"]


def owner_task(**more: Any) -> Task:
    base: dict[str, Any] = {
        "purpose": "test.owner",
        "instructions": "Say who owns the service, citing the context.",
        "input": {"question": "Who owns payment-api?"},
        "context": CONTEXT,
        "output": Owner,
        "check": grounded,
        "needs": Needs(structured=True),
        "tier": Tier.FAST,
        "ref": "intention:42",
    }
    return Task(**{**base, **more})


async def test_a_task_is_done_with_its_context_checked_and_kept(workspace: uuid.UUID) -> None:
    script = Script(gemini({"owner": "Payments", "cites": ["relationship:owned"]}))
    done = await _run(workspace, script, owner_task())

    assert done.ok and done.value == Owner(owner="Payments", cites=["relationship:owned"])
    assert (done.provider, done.model, done.version) == (
        "google",
        "gemini-3.8-flash",
        "gemini-3.8-flash-001",
    )
    # Its instructions, then LEKA's own rules; the task and its context, apart.
    body = script.asked[0]
    system = body["systemInstruction"]["parts"][0]["text"]
    assert system.startswith("Say who owns the service") and GUARDRAILS in system
    said = json.loads(body["contents"][0]["parts"][0]["text"])
    assert said["task"] == {"question": "Who owns payment-api?"}
    assert [item["id"] for item in said["context"]] == ["entity:payment-api", "relationship:owned"]
    assert said["context"][0]["sources"] == ["github"]

    [run], [call] = await _kept(workspace)
    assert (run.id, run.purpose, run.ref, run.status) == (
        done.run_id,
        "test.owner",
        "intention:42",
        "succeeded",
    )
    assert (run.provider, run.model, run.version, run.calls) == (
        "google",
        "gemini-3.8-flash",
        "gemini-3.8-flash-001",
        1,
    )
    assert (run.tokens_in, run.tokens_out, run.context_ref, run.context_items) == (
        500,
        40,
        "context:test:v1",
        2,
    )
    assert run.cost_usd == pytest.approx(500 * 0.75 / 1e6 + 40 * 3.75 / 1e6)
    assert call.run_id == run.id


async def test_an_answer_is_checked_before_it_is_used_and_asked_again(
    workspace: uuid.UUID,
) -> None:
    # Its shape, then its own check: a citation it was not given.
    script = Script(
        gemini({"owner": 42}),
        gemini({"owner": "Infra", "cites": ["invented"]}),
    )
    done = await _run(workspace, script, owner_task())
    assert (done.status, done.value) == ("invalid", None)
    [run], calls = await _kept(workspace)
    assert run.status == "invalid"
    assert [c.status for c in calls] == ["invalid", "invalid"]
    assert "Not what was asked" in (calls[1].error or "")

    # Wrong once, right the second time: used.
    script = Script(
        gemini({"owner": "Infra", "cites": ["invented"]}),
        gemini({"owner": "Payments", "cites": ["entity:payment-api"]}),
    )
    assert (await _run(workspace, script, owner_task())).value.owner == "Payments"


async def test_how_it_ended_is_a_status_never_an_exception(workspace: uuid.UUID) -> None:
    # No model can: no_model, nothing asked.
    nothing = await _run(workspace, Script(), owner_task(), keys={})
    assert (nothing.status, nothing.calls) == ("no_model", 0)

    # Every model refused: failed, every try kept.
    refused = httpx.Response(401, json={"error": {"message": "API key not valid"}})
    done = await _run(workspace, Script(refused), owner_task())
    assert done.status == "failed" and "API key not valid" in (done.error or "")

    # Its budget spent: timed_out.
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return gemini({"owner": "late"})

    timed = await _run(workspace, Script(slow), owner_task(budget=0.05))
    assert timed.status == "timed_out"

    runs, _ = await _kept(workspace)
    assert sorted(r.status for r in runs) == ["failed", "no_model", "timed_out"]


async def test_a_model_reads_never_acts(workspace: uuid.UUID) -> None:
    async def restart(arguments: Any) -> str:
        return "restarted"

    with pytest.raises(SensitiveToolError, match="cannot be given to a model"):
        RuntimeTool("restart", "Restart a service.", {"type": "object"}, restart, effect="act")

    read: list[dict[str, Any]] = []

    async def lookup(arguments: Any) -> str:
        read.append(dict(arguments))
        return json.dumps({"owner": "Payments"})

    tool = RuntimeTool(
        "lookup",
        "Look a service up in the company model.",
        {"type": "object", "properties": {"name": {"type": "string"}}},
        lookup,
    )
    script = Script(calling("lookup", {"name": "payment-api"}), gemini("Payments owns it."))
    done = await _run(
        workspace,
        script,
        Task(
            purpose="agent:test",
            instructions="",
            input="",
            # An agent writes its own conversation (ADR 004): kept as given.
            messages=[Message.system("You are a test agent."), Message.user("Who owns it?")],
            tools=[tool],
            needs=Needs(tools=True),
            tier=Tier.DEEP,
        ),
    )
    assert (done.status, done.text, done.calls) == ("succeeded", "Payments owns it.", 2)
    assert read == [{"name": "payment-api"}]
    first = script.asked[0]
    assert first["systemInstruction"]["parts"][0]["text"] == "You are a test agent."
    assert first["contents"][0]["parts"][0]["text"] == "Who owns it?"

    # Tools in rounds without end, or past its budget: said, not raised.
    loops = Script(*[calling("lookup", {"name": "x"}) for _ in range(7)])
    endless = await _run(
        workspace,
        loops,
        Task(
            purpose="agent:loop",
            instructions="Look things up.",
            input="Go.",
            tools=[tool],
            needs=Needs(tools=True),
        ),
    )
    assert (endless.status, endless.error) == ("failed", "tool_rounds")


async def test_tools_then_a_shape_the_last_round_answers_with_what_it_read(
    workspace: uuid.UUID,
) -> None:
    """LEKA's analyst: tools, an answer in its shape — and, its rounds spent,
    made to answer rather than fail."""

    async def lookup(arguments: Any) -> str:
        return json.dumps({"id": "entity:payment-api", "owner": "Payments"})

    tool = RuntimeTool(
        "lookup",
        "Look a service up.",
        {"type": "object", "properties": {"name": {"type": "string"}}},
        lookup,
    )
    script = Script(
        calling("lookup", {"name": "payment-api"}),
        calling("lookup", {"name": "payment-api"}),
        gemini({"owner": "Payments", "cites": ["relationship:owned"]}),
    )
    done = await _run(
        workspace,
        script,
        owner_task(tools=[tool], needs=Needs(structured=True, tools=True), rounds=3, conclude=True),
    )
    assert done.ok and done.value == Owner(owner="Payments", cites=["relationship:owned"])
    assert done.calls == 3
    # The shape asked every round, beside the tools; the last round may not
    # call one.
    assert all("responseJsonSchema" in body["generationConfig"] for body in script.asked)
    modes = [body["toolConfig"]["functionCallingConfig"]["mode"] for body in script.asked]
    assert modes == ["AUTO", "AUTO", "NONE"]


async def test_what_a_model_was_asked_is_remembered_on_its_facts(workspace: uuid.UUID) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            runtime = LLMRuntime(session, workspace)
            assert await runtime.asked("enrichment.summary", ["a", "b"]) == {}
            await runtime.remember("enrichment.summary", {"a": "d1", "b": "d2"}, answered={"a"})
            await session.commit()
        async with session_factory() as session:
            runtime = LLMRuntime(session, workspace)
            assert await runtime.asked("enrichment.summary", ["a", "b", "c"]) == {
                "a": "d1",
                "b": "d2",
            }
            # Another purpose knows nothing of it.
            assert await runtime.asked("other", ["a"]) == {}
            # Asked again on new facts: what is remembered follows.
            await runtime.remember("enrichment.summary", {"b": "d3"}, answered={"b"})
            await session.commit()
            assert (await runtime.asked("enrichment.summary", ["b"])) == {"b": "d3"}


async def test_tokens_read_from_the_cache_are_billed_at_their_price(workspace: uuid.UUID) -> None:
    cached = httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": json.dumps({"owner": "P"})}]}}
            ],
            "usageMetadata": {
                "promptTokenCount": 1000,
                "cachedContentTokenCount": 800,
                "candidatesTokenCount": 40,
                "thoughtsTokenCount": 60,
            },
            "modelVersion": "gemini-3.8-flash-001",
        },
    )
    done = await _run(workspace, Script(cached), owner_task(check=None))
    assert done.ok
    _, calls = await _kept(workspace)
    (call,) = calls
    assert (call.tokens_in, call.tokens_cached, call.tokens_out) == (1000, 800, 100)
    # 200 at 0.75, 800 cached at 0.075, 100 out (thinking included) at 3.75,
    # dollars a million.
    assert call.cost_usd == round((200 * 0.75 + 800 * 0.075 + 100 * 3.75) / 1_000_000, 6)


def test_a_context_assembled_is_given_as_ranked_and_cut_to_size() -> None:
    def element(position: int, text: str) -> Any:
        return SimpleNamespace(
            position=position,
            kind="entity",
            ref_id=uuid.UUID(int=position),
            ref_type="service",
            label=f"thing {position}",
            text=text,
            provenance=SimpleNamespace(
                sources=[SimpleNamespace(kind="backstage", name="Catalogue")]
            ),
        )

    context = SimpleNamespace(
        context_id=uuid.UUID(int=99),
        version=3,
        elements=[element(2, "second"), element(1, "first"), element(3, "x" * 500)],
    )
    pack = ContextPack.of_context(context, characters=200)
    assert [i.text for i in pack.items] == ["first", "second"]
    assert pack.items[0].id == f"entity:{uuid.UUID(int=1)}"
    assert pack.items[0].sources == ("backstage",)
    assert (pack.ref, pack.left_out) == (f"context:{uuid.UUID(int=99)}:v3", 1)
