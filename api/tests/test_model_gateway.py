"""The model gateway (LEKA-394), end to end against the database — no
network: each provider is a scripted transport.

What these protect: LEKA's default model answers and the call is kept —
purpose, provider, model, the version that answered, tokens, its cost at
list price; a provider busy is tried again, then the fallback answers, and
every try is kept; a structured answer that does not match is asked again,
and kept as invalid with what it cost; a model asking for tools gets their
results, signed calls sent back, until it answers; a workspace's own model
answers before LEKA's, one refusing its key is marked failed and LEKA's
answers instead — unless the workspace said "ours only"; a model too slow
for the budget, or none configured, raises rather than making anything up;
a test of the workspace's model says whether it answered.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select

from leka.capabilities import (
    Gateway,
    Message,
    ModelCall,
    ModelRate,
    NoModelError,
    Request,
    Tier,
    Tool,
    WorkspaceModel,
)
from leka.db import session_factory, system_scope, workspace_scope
from leka.platform import Workspace, secret_box

pytestmark = pytest.mark.integration

KEYS: dict[str, str | None] = {"google": "g-key", "mistral": "m-key", "anthropic": None}
DEFAULT = ("google", "gemini-3.8-flash")
FALLBACKS = [("mistral", "mistral-large-latest")]


class Verdict(BaseModel):
    goal: str
    confidence: float


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


def chat(text: str, model: str = "mistral-large-2512") -> dict[str, Any]:
    return {
        "id": "m-1",
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


Answer = dict[str, Any] | httpx.Response


class Script:
    """Answers by host, in order — and keeps what was asked."""

    def __init__(self, answers: Mapping[str, Sequence[Answer]] | None = None) -> None:
        self.answers = {host: list(said) for host, said in (answers or {}).items()}
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        answer = self.answers[request.url.host].pop(0)
        return answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


GOOGLE = "generativelanguage.googleapis.com"
MISTRAL = "api.mistral.ai"


@pytest.fixture
async def workspace() -> AsyncIterator[uuid.UUID]:
    with system_scope():
        async with session_factory() as session:
            found = Workspace(name="Gateway", slug=f"gateway-{uuid.uuid4().hex[:10]}")
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


async def _ask(
    workspace_id: uuid.UUID,
    script: Script,
    act: Callable[[Gateway], Any],
    *,
    keys: dict[str, str | None] = KEYS,
    sleeps: list[float] | None = None,
) -> Any:
    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    with workspace_scope(workspace_id):
        async with session_factory() as session:
            gateway = Gateway(
                session,
                workspace_id,
                transport=script.transport,
                keys=keys,
                default=DEFAULT,
                fallbacks=FALLBACKS,
                retries=1,
                sleep=sleep,
            )
            try:
                return await act(gateway)
            finally:
                await session.commit()


async def _calls(workspace_id: uuid.UUID) -> list[ModelCall]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(ModelCall)
                        .where(ModelCall.workspace_id == workspace_id)
                        .order_by(ModelCall.at, ModelCall.attempt)
                    )
                ).all()
            )


async def _own(workspace_id: uuid.UUID, *, exclusive: bool = False) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            session.add(
                WorkspaceModel(
                    workspace_id=workspace_id,
                    id=uuid.uuid4(),
                    provider="mistral",
                    model="mistral-small-latest",
                    key_ciphertext=secret_box.encrypt("own-key"),
                    key_hint="-key",
                    enabled=True,
                    exclusive=exclusive,
                    changed_at=datetime.now(UTC),
                )
            )
            await session.commit()


def ask(purpose: str = "test", **more: Any) -> Request:
    return Request(purpose=purpose, messages=[Message.user("Why is payment-api down?")], **more)


async def test_the_default_answers_and_the_call_is_kept_with_what_it_cost(
    workspace: uuid.UUID,
) -> None:
    script = Script({GOOGLE: [gemini("Because of the 14:02 deploy.")]})
    done = await _ask(
        workspace, script, lambda g: g.complete(ask("intention.answer", ref="intention:42"))
    )
    assert done.text == "Because of the 14:02 deploy."
    assert script.asked[0].headers["x-goog-api-key"] == "g-key"
    [call] = await _calls(workspace)
    assert (call.purpose, call.ref, call.provider, call.model, call.version) == (
        "intention.answer",
        "intention:42",
        "google",
        "gemini-3.8-flash",
        "gemini-3.8-flash-001",
    )
    assert (call.route, call.owner, call.status, call.attempt) == ("default", "leka", "ok", 1)
    assert (call.tokens_in, call.tokens_out) == (1000, 300)
    # 1000 x 0.75 + 300 x 3.75, per million, at today's introductory price.
    assert call.cost_usd == pytest.approx(0.001875)


async def test_the_call_is_priced_with_the_rate_in_force_and_says_it_was_measured(
    workspace: uuid.UUID,
) -> None:
    script = Script({GOOGLE: [gemini("Because of the 14:02 deploy.")]})
    await _ask(workspace, script, lambda g: g.complete(ask()))
    [call] = await _calls(workspace)
    with system_scope():
        async with session_factory() as session:
            rate = await session.get(ModelRate, call.rate_id)
    assert rate is not None
    assert (rate.provider, rate.model, rate.per_million_in) == ("google", "gemini-3.8-flash", 0.75)
    assert call.usage_reported is True


async def test_an_answer_without_its_usage_is_kept_unknown_not_free(
    workspace: uuid.UUID,
) -> None:
    said = gemini("Because of the 14:02 deploy.")
    del said["usageMetadata"]
    script = Script({GOOGLE: [said]})
    await _ask(workspace, script, lambda g: g.complete(ask()))
    [call] = await _calls(workspace)
    assert (call.usage_reported, call.tokens_in, call.cost_usd, call.rate_id) == (
        False,
        0,
        None,
        None,
    )


async def _spent(workspace_id: uuid.UUID, cost_usd: float) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            session.add(
                ModelCall(
                    workspace_id=workspace_id,
                    id=uuid.uuid4(),
                    purpose="intention.understanding",
                    tier="fast",
                    provider="google",
                    model="gemini-3.8-flash",
                    route="default",
                    owner="leka",
                    status="ok",
                    cost_usd=cost_usd,
                    at=datetime.now(UTC),
                )
            )
            await session.commit()


async def test_credits_spent_leka_s_models_are_refused_never_billed_past(
    workspace: uuid.UUID,
) -> None:
    # Free: 200 credits, $2 of LEKA's model cost — spent.
    await _spent(workspace, 2.0)
    script = Script({GOOGLE: [gemini("Not asked.")]})
    with pytest.raises(NoModelError) as raised:
        await _ask(workspace, script, lambda g: g.complete(ask()))
    assert raised.value.reason == "limited"
    assert "credits" in str(raised.value)
    assert script.asked == []


async def test_credits_spent_the_workspace_s_own_model_still_answers(
    workspace: uuid.UUID,
) -> None:
    await _spent(workspace, 2.0)
    await _own(workspace)
    script = Script({MISTRAL: [chat("From our own Mistral.")]})
    done = await _ask(workspace, script, lambda g: g.complete(ask()))
    assert done.text == "From our own Mistral."
    assert [c.owner for c in await _calls(workspace)][-1] == "workspace"


async def test_a_busy_provider_is_tried_again_then_the_fallback_answers(
    workspace: uuid.UUID,
) -> None:
    busy = httpx.Response(503, json={"error": {"message": "overloaded"}})
    script = Script({GOOGLE: [busy, busy], MISTRAL: [chat("From Mistral.")]})
    sleeps: list[float] = []
    done = await _ask(workspace, script, lambda g: g.complete(ask()), sleeps=sleeps)
    assert (done.provider, done.text) == ("mistral", "From Mistral.")
    assert sleeps == [1.0]
    calls = await _calls(workspace)
    assert [(c.provider, c.attempt, c.status, c.route) for c in calls] == [
        ("google", 1, "failed", "default"),
        ("google", 2, "failed", "default"),
        ("mistral", 1, "ok", "fallback"),
    ]
    assert calls[0].error == "503: overloaded"


async def test_a_structured_answer_is_checked_and_asked_again(workspace: uuid.UUID) -> None:
    script = Script(
        {
            GOOGLE: [
                gemini('{"goal": "explain_cause"}'),
                gemini('```json\n{"goal": "explain_cause", "confidence": 0.8}\n```'),
            ]
        }
    )
    read = await _ask(workspace, script, lambda g: g.structured(ask(tier=Tier.FAST), Verdict))
    assert read.value == Verdict(goal="explain_cause", confidence=0.8)
    calls = await _calls(workspace)
    assert [c.status for c in calls] == ["invalid", "ok"]
    # Answered, and billed: an invalid answer keeps its tokens.
    assert calls[0].tokens_in == 1000
    assert "confidence" in (calls[0].error or "")
    body = json.loads(script.asked[0].content)
    assert body["generationConfig"]["responseJsonSchema"]["required"] == ["goal", "confidence"]


async def test_tools_are_called_until_the_model_answers(workspace: uuid.UUID) -> None:
    script = Script(
        {
            GOOGLE: [
                gemini(call={"name": "lookup", "args": {"name": "payment-api"}, "id": "c1"}),
                gemini("Payments owns it."),
            ]
        }
    )
    looked: list[dict[str, Any]] = []

    async def lookup(arguments: Any) -> str:
        looked.append(dict(arguments))
        return json.dumps({"owner": "Payments"})

    tool = Tool("lookup", "Look a service up.", {"type": "object", "properties": {}})
    done = await _ask(
        workspace, script, lambda g: g.run_tools(ask(tools=[tool]), {"lookup": lookup})
    )
    assert done.text == "Payments owns it."
    assert looked == [{"name": "payment-api"}]
    second = json.loads(script.asked[1].content)["contents"]
    assert second[1]["parts"][0]["thoughtSignature"] == "sig-1"
    assert second[2]["parts"][0]["functionResponse"]["response"] == {
        "result": '{"owner": "Payments"}'
    }
    assert [c.tool_calls for c in await _calls(workspace)] == [1, 0]


async def test_a_workspace_model_answers_first_and_a_refused_key_falls_back(
    workspace: uuid.UUID,
) -> None:
    await _own(workspace)
    script = Script({MISTRAL: [chat("Own model.", "mistral-small-2603")]})
    done = await _ask(workspace, script, lambda g: g.complete(ask()))
    assert done.text == "Own model."
    assert script.asked[0].headers["authorization"] == "Bearer own-key"

    refused = httpx.Response(401, json={"message": "Unauthorized"})
    script = Script({MISTRAL: [refused], GOOGLE: [gemini("LEKA's model.")]})
    done = await _ask(workspace, script, lambda g: g.complete(ask()))
    assert done.provider == "google"
    calls = await _calls(workspace)
    assert [(c.owner, c.status) for c in calls][-2:] == [("workspace", "failed"), ("leka", "ok")]
    with workspace_scope(workspace):
        async with session_factory() as session:
            row = await session.scalar(select(WorkspaceModel))
            assert row is not None
            assert row.status == "failed"
            assert "401" in (row.status_detail or "")


async def test_ours_only_means_never_leka_and_nothing_made_up(workspace: uuid.UUID) -> None:
    await _own(workspace, exclusive=True)
    refused = httpx.Response(401, json={"message": "Unauthorized"})
    script = Script({MISTRAL: [refused]})
    with pytest.raises(NoModelError) as raised:
        await _ask(workspace, script, lambda g: g.complete(ask()))
    assert raised.value.attempts[0].owner == "workspace"
    assert all(r.url.host != GOOGLE for r in script.asked)


async def test_no_model_configured_raises(workspace: uuid.UUID) -> None:
    with pytest.raises(NoModelError, match="No language model is configured"):
        await _ask(workspace, Script(), lambda g: g.complete(ask()), keys={})


async def test_a_budget_spent_raises_rather_than_wait(workspace: uuid.UUID) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        import asyncio

        await asyncio.sleep(5)
        return httpx.Response(200, json=gemini("late"))

    with workspace_scope(workspace):
        async with session_factory() as session:
            gateway = Gateway(
                session,
                workspace,
                transport=httpx.MockTransport(slow),
                keys=KEYS,
                default=DEFAULT,
                fallbacks=[],
            )
            with pytest.raises(NoModelError, match="No answer in time"):
                await gateway.complete(ask(), budget=0.05)


async def test_testing_the_workspace_model_says_whether_it_answered(workspace: uuid.UUID) -> None:
    await _own(workspace)
    script = Script({MISTRAL: [chat("OK", "mistral-small-2603")]})
    tested = await _ask(workspace, script, lambda g: g.test())
    assert (tested.ok, tested.model, tested.version) == (
        True,
        "mistral-small-latest",
        "mistral-small-2603",
    )
    with workspace_scope(workspace):
        async with session_factory() as session:
            row = await session.scalar(select(WorkspaceModel))
            assert row is not None
            assert row.status == "ok"
