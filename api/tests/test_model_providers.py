"""The providers behind the model gateway (LEKA-394), each in its own
words — no network: every answer is the one the vendor documents.

What these protect: Gemini is asked by its own API — the key in its header,
the system apart, how long it may think by the tier, the schema of a
structured answer, the tools as function declarations — and read back with
the version that answered, the thinking billed as output, a tool call's
signature kept; that signature goes back with the call on the next turn,
with the tool's result. Mistral, OpenAI and a company's Azure OpenAI speak
the chat-completions shape, each with its own words (Mistral's "any", an
Azure deployment in the address); Anthropic gives a structured answer as
the one tool it must call. A provider's refusal says whether another try
may help, and how long it asks to wait. The router offers the workspace's
model first, LEKA's default next, then the fallbacks; passes over what
cannot do what is asked, and says why; a workspace that said "ours only"
gets nothing else.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from leka.capabilities.gateway import (
    AZURE_OPENAI,
    MISTRAL,
    OPENAI,
    Anthropic,
    Endpoint,
    Google,
    Message,
    Needs,
    Output,
    Own,
    ProviderError,
    Request,
    Role,
    Tier,
    Tool,
    ToolCall,
    ToolChoice,
    plain_schema,
    profile,
    route,
)
from leka.capabilities.gateway.assignment import Assignment
from leka.capabilities.gateway.contract import Call


class Verdict(BaseModel):
    goal: str
    confidence: float


class Wrapper(BaseModel):
    verdict: Verdict
    notes: list[str]


LOOKUP = Tool(
    "lookup",
    "Look a service up in the company model.",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)


def _gemini(*, text: str | None = None, call: dict[str, Any] | None = None) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": "thinking…", "thought": True}]
    if text is not None:
        parts.append({"text": text})
    if call is not None:
        parts.append({"functionCall": call, "thoughtSignature": "sig-1"})
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
        "usageMetadata": {
            "promptTokenCount": 1000,
            "candidatesTokenCount": 200,
            "thoughtsTokenCount": 100,
        },
        "modelVersion": "gemini-3.8-flash-001",
        "responseId": "resp-1",
    }


async def _ask(
    vendor: Any, call: Call, answer: dict[str, Any] | httpx.Response
) -> tuple[Any, httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        done = await vendor.complete(call, client)
    return done, seen[0]


def _call(provider: str, model: str, request: Request, **endpoint: Any) -> Call:
    found = profile(provider, model)
    return Call(
        Endpoint(provider=provider, api_key="key-1", **endpoint),
        model,
        request,
        thinking=found.thinking,
        sends_temperature=found.sends_temperature,
        forces_tools=found.forces_tools,
        responses=found.responses,
    )


async def test_gemini_is_asked_in_its_own_words_and_read_back_whole() -> None:
    request = Request(
        purpose="test",
        messages=[Message.system("You are LEKA."), Message.user("Why is payment-api down?")],
        tier=Tier.FAST,
        temperature=0.1,
        output=Output.of(Verdict),
    )
    done, sent = await _ask(
        Google(),
        _call("google", "gemini-3.8-flash", request),
        _gemini(text='{"goal": "explain_cause", "confidence": 0.9}'),
    )
    assert sent.url.path == "/v1beta/models/gemini-3.8-flash:generateContent"
    assert sent.headers["x-goog-api-key"] == "key-1"
    body = json.loads(sent.content)
    assert body["systemInstruction"] == {"parts": [{"text": "You are LEKA."}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "Why is payment-api down?"}]}]
    config = body["generationConfig"]
    # Gemini 3 is left at its own temperature; the tier says how long it thinks.
    assert "temperature" not in config
    assert config["thinkingConfig"] == {"thinkingLevel": "low"}
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"]["required"] == ["goal", "confidence"]

    # The thought is not the answer; the version is what answered; thinking
    # is billed as output.
    assert done.text == '{"goal": "explain_cause", "confidence": 0.9}'
    assert done.version == "gemini-3.8-flash-001"
    assert (done.usage.tokens_in, done.usage.tokens_out, done.usage.tokens_thinking) == (
        1000,
        300,
        100,
    )
    assert done.request_id == "resp-1"


async def test_a_gemini_tool_call_keeps_its_signature_and_goes_back_with_its_result() -> None:
    request = Request(
        purpose="test",
        messages=[Message.user("Who owns payment-api?")],
        tools=[LOOKUP],
        tool_choice=ToolChoice.REQUIRED,
    )
    done, sent = await _ask(
        Google(),
        _call("google", "gemini-3.8-flash", request),
        _gemini(call={"name": "lookup", "args": {"name": "payment-api"}, "id": "c1"}),
    )
    body = json.loads(sent.content)
    declared = body["tools"][0]["functionDeclarations"][0]
    assert declared["name"] == "lookup"
    assert declared["parametersJsonSchema"]["required"] == ["name"]
    assert body["toolConfig"] == {"functionCallingConfig": {"mode": "ANY"}}
    assert done.tool_calls == (
        ToolCall("c1", "lookup", {"name": "payment-api"}, signature="sig-1"),
    )

    # Next turn: the call, signed, then what the tool returned.
    follow = Request(
        purpose="test",
        messages=[
            Message.user("Who owns payment-api?"),
            Message(Role.ASSISTANT, "", tool_calls=done.tool_calls),
            Message(Role.TOOL, '{"owner": "Payments"}', tool_call_id="c1", name="lookup"),
        ],
        tools=[LOOKUP],
    )
    _, sent = await _ask(
        Google(), _call("google", "gemini-3.8-flash", follow), _gemini(text="Payments.")
    )
    contents = json.loads(sent.content)["contents"]
    assert contents[1] == {
        "role": "model",
        "parts": [
            {
                "functionCall": {"name": "lookup", "args": {"name": "payment-api"}, "id": "c1"},
                "thoughtSignature": "sig-1",
            }
        ],
    }
    assert contents[2]["parts"][0]["functionResponse"] == {
        "name": "lookup",
        "id": "c1",
        "response": {"result": '{"owner": "Payments"}'},
    }


async def test_mistral_and_azure_speak_chat_completions_each_in_their_words() -> None:
    request = Request(
        purpose="test",
        messages=[Message.user("Who owns payment-api?")],
        tools=[LOOKUP],
        tool_choice=ToolChoice.REQUIRED,
        temperature=0.2,
    )
    answer = {
        "id": "m-1",
        "model": "mistral-large-2512",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "t1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"name": "payment-api"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 40,
            "completion_tokens": 12,
            "prompt_tokens_details": {"cached_tokens": 32},
        },
    }
    done, sent = await _ask(MISTRAL, _call("mistral", "mistral-large-latest", request), answer)
    # What it read from its cache, said apart: billed less.
    assert (done.usage.tokens_in, done.usage.tokens_cached) == (40, 32)
    assert str(sent.url) == "https://api.mistral.ai/v1/chat/completions"
    assert sent.headers["authorization"] == "Bearer key-1"
    body = json.loads(sent.content)
    assert (body["model"], body["tool_choice"], body["temperature"]) == (
        "mistral-large-latest",
        "any",
        0.2,
    )
    assert done.tool_calls[0].arguments == {"name": "payment-api"}
    assert done.version == "mistral-large-2512"

    # A company's Azure OpenAI: its deployment in the address, its key header.
    plain = Request(purpose="test", messages=[Message.user("Hello")], output=Output.of(Verdict))
    _, sent = await _ask(
        AZURE_OPENAI,
        _call(
            "azure_openai",
            "gpt-prod",
            plain,
            base_url="https://acme.openai.azure.com/",
            api_version="2024-10-21",
        ),
        {"choices": [{"message": {"content": "{}"}}]},
    )
    assert str(sent.url) == (
        "https://acme.openai.azure.com/openai/deployments/gpt-prod/chat/completions"
        "?api-version=2024-10-21"
    )
    assert sent.headers["api-key"] == "key-1"
    body = json.loads(sent.content)
    assert "model" not in body
    assert body["response_format"]["type"] == "json_schema"


async def test_anthropic_gives_a_structured_answer_as_the_tool_it_must_call() -> None:
    request = Request(
        purpose="test",
        messages=[Message.system("Be brief."), Message.user("Classify this.")],
        output=Output.of(Verdict),
    )
    answer = {
        "id": "msg-1",
        "model": "claude-sonnet-5",
        "content": [
            {
                "type": "tool_use",
                "id": "x",
                "name": "Verdict",
                "input": {"goal": "a", "confidence": 1},
            }
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 30, "output_tokens": 9, "cache_read_input_tokens": 70},
    }
    done, sent = await _ask(Anthropic(), _call("anthropic", "claude-sonnet-5", request), answer)
    # Its cache reads come apart from input_tokens: counted in, said cached.
    assert (done.usage.tokens_in, done.usage.tokens_cached) == (100, 70)
    body = json.loads(sent.content)
    assert body["system"] == "Be brief."
    assert body["tool_choice"] == {"type": "tool", "name": "Verdict"}
    assert sent.headers["anthropic-version"] == "2023-06-01"
    assert json.loads(done.text) == {"goal": "a", "confidence": 1}
    assert done.tool_calls == ()


class Bounded(BaseModel):
    score: int = Field(ge=0, le=10)
    reasons: list[str] = Field(max_length=3)
    verdict: Verdict


async def test_claude_5_5_is_asked_its_answer_as_json_never_made_to_call_a_tool() -> None:
    # 2026-10-20: Claude 5.5 refuses a forced tool and a temperature (400).
    request = Request(
        purpose="test",
        messages=[Message.user("Classify this.")],
        output=Output.of(Bounded),
        temperature=0.2,
    )
    answer = {
        "id": "msg-1",
        "model": "claude-sonnet-5-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "s"},
            {
                "type": "text",
                "text": '{"score": 3, "reasons": [], "verdict": {"goal": "a", "confidence": 1}}',
            },
        ],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 30, "output_tokens": 9},
    }
    done, sent = await _ask(Anthropic(), _call("anthropic", "claude-sonnet-5-5", request), answer)
    body = json.loads(sent.content)
    assert "tool_choice" not in body and "tools" not in body and "temperature" not in body
    schema = body["output_config"]["format"]["schema"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    # Every object closed, the bounds it refuses left out.
    assert schema["additionalProperties"] is False
    assert schema["properties"]["verdict"]["additionalProperties"] is False
    assert schema["properties"]["score"] == {"type": "integer"}
    assert "maxItems" not in schema["properties"]["reasons"]
    assert json.loads(done.text)["score"] == 3


async def test_claude_5_5_s_thinking_goes_back_whole_with_its_tool_calls() -> None:
    request = Request(
        purpose="test",
        messages=[Message.user("Who owns payment-api?")],
        tools=[LOOKUP],
        tool_choice=ToolChoice.REQUIRED,
    )
    thought = {"type": "thinking", "thinking": "", "signature": "opaque-1"}
    answer = {
        "id": "msg-1",
        "model": "claude-opus-5-5",
        "content": [
            thought,
            {"type": "tool_use", "id": "c1", "name": "lookup", "input": {"name": "payment-api"}},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 30, "output_tokens": 9},
    }
    done, sent = await _ask(Anthropic(), _call("anthropic", "claude-opus-5-5", request), answer)
    # Left to it, never made to.
    assert json.loads(sent.content)["tool_choice"] == {"type": "auto"}

    follow = Request(
        purpose="test",
        messages=[
            Message.user("Who owns payment-api?"),
            Message(Role.ASSISTANT, "", tool_calls=done.tool_calls),
            Message(Role.TOOL, '{"owner": "Payments"}', tool_call_id="c1", name="lookup"),
        ],
        tools=[LOOKUP],
    )
    _, sent = await _ask(Anthropic(), _call("anthropic", "claude-opus-5-5", follow), answer)
    turn = json.loads(sent.content)["messages"][1]["content"]
    assert turn[0] == thought and turn[1]["type"] == "tool_use"

    # A call another provider signed brings no thinking of Claude's.
    gemini = Message(
        Role.ASSISTANT, "", tool_calls=(ToolCall("c1", "lookup", {}, signature="sig-1"),)
    )
    mixed = Request(purpose="test", messages=[follow.messages[0], gemini, follow.messages[2]])
    _, sent = await _ask(Anthropic(), _call("anthropic", "claude-opus-5-5", mixed), answer)
    assert json.loads(sent.content)["messages"][1]["content"][0]["type"] == "tool_use"


@pytest.mark.parametrize(
    ("status", "retryable", "wait"),
    [(429, True, 7.0), (503, True, 7.0), (401, False, 7.0), (400, False, 7.0)],
)
async def test_a_refusal_says_whether_another_try_may_help(
    status: int, retryable: bool, wait: float
) -> None:
    refused = httpx.Response(
        status, json={"error": {"message": "nope"}}, headers={"retry-after": "7"}
    )
    request = Request(purpose="test", messages=[Message.user("Hi")])
    with pytest.raises(ProviderError) as raised:
        await _ask(Google(), _call("google", "gemini-3.8-flash", request), refused)
    assert raised.value.retryable is retryable
    assert raised.value.retry_after == wait
    assert str(raised.value) == f"{status}: nope"


def test_a_schema_is_sent_with_its_references_inlined() -> None:
    schema = plain_schema(Wrapper)
    assert "$defs" not in json.dumps(schema)
    assert schema["properties"]["verdict"]["required"] == ["goal", "confidence"]
    assert "title" not in schema


def test_a_field_called_title_is_a_field_and_is_kept() -> None:
    """The schema's own "title" label goes; a property named "title" stays.
    Dropping both left the architect's deck schema "requiring" a property it
    no longer had: Gemini answered 400, and no deck was ever drawn."""
    from leka.capabilities.deliverables import ArchitectureDeck

    def requires_what_it_has(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                assert set(node.get("required", [])) <= set(properties), node.get("required")
            for value in node.values():
                requires_what_it_has(value)
        elif isinstance(node, list):
            for value in node:
                requires_what_it_has(value)

    schema = plain_schema(ArchitectureDeck)
    requires_what_it_has(schema)
    band = schema["properties"]["processes"]["items"]["properties"]["bands"]["items"]
    assert "title" in band["properties"] and "title" in band["required"]
    assert "title" not in schema


def test_gemini_costs_what_google_lists_and_its_price_doubles_in_2027() -> None:
    flash = profile("google", "gemini-3.8-flash")
    assert flash.cost(1_000_000, 1_000_000, datetime(2026, 10, 9, tzinfo=UTC)) == 4.5
    assert flash.cost(1_000_000, 1_000_000, datetime(2027, 1, 2, tzinfo=UTC)) == 9.0
    # A model without a published price is not guessed.
    assert profile("azure_openai", "gpt-prod").cost(10, 10) is None
    assert profile("mistral", "codestral-latest").cost(10, 10) is None


def test_mistral_costs_what_it_lists_from_the_day_it_was_read() -> None:
    # 2026-10-21: Medium and Small had no price, Large's cache none either.
    day = datetime(2026, 10, 22, tzinfo=UTC)
    assert profile("mistral", "mistral-small-latest").cost(1_000_000, 1_000_000, day) == 0.75
    assert profile("mistral", "mistral-medium-latest").cost(1_000_000, 1_000_000, day) == 9.0
    large = profile("mistral", "mistral-large-latest").price(day)
    assert large is not None and large.per_million_cached == 0.05


# ── routing ──────────────────────────────────────────────────────────────────

KEYS: dict[str, str | None] = {"google": "g", "mistral": "m", "anthropic": None}
DEFAULT = ("google", "gemini-3.8-flash")
# What agents/models.yaml gives an agent: its model, no fallback approved.
ASSIGNED = Assignment(model=DEFAULT)


def _order(routing: Any) -> list[tuple[str, str, str]]:
    return [(r.endpoint.provider, r.profile.model, r.why) for r in routing.routes]


def test_the_assigned_model_answers_then_its_approved_fallback_and_nothing_else() -> None:
    # LEKA-530: never another model LEKA holds a key for, never one by task.
    routing = route(
        Needs(),
        own=None,
        keys=ALL_KEYS,
        assignment=Assignment(DEFAULT, fallbacks=(("mistral", "mistral-large-latest"),)),
    )
    assert _order(routing) == [
        ("google", "gemini-3.8-flash", "assigned"),
        ("mistral", "mistral-large-latest", "fallback"),
    ]


def test_a_workspace_model_comes_first_and_ours_only_means_nothing_else() -> None:
    own = Own(Endpoint("azure_openai", "k", base_url="https://acme", owner="workspace"), "gpt-prod")
    routing = route(Needs(), own=own, keys=KEYS, assignment=ASSIGNED)
    assert _order(routing) == [
        ("azure_openai", "gpt-prod", "own"),
        ("google", "gemini-3.8-flash", "assigned"),
    ]

    only = route(
        Needs(),
        own=Own(own.endpoint, own.model, exclusive=True),
        keys=KEYS,
        assignment=ASSIGNED,
    )
    assert _order(only) == [("azure_openai", "gpt-prod", "own")]
    assert only.passed[-1].reason == "exclusive"


def test_what_a_step_needs_its_model_cannot_do_is_said_never_handed_to_another() -> None:
    # A context past what Mistral Large takes: not tried, said — and no
    # other model in its place.
    large = Assignment(("mistral", "mistral-large-latest"))
    routing = route(Needs(context=500_000), own=None, keys=ALL_KEYS, assignment=large)
    assert routing.routes == ()
    assert [(p.model, p.reason) for p in routing.passed] == [("mistral-large-latest", "context")]
    # No key for the assigned model: said, and nothing answers in its place.
    without = route(Needs(), own=None, keys={"mistral": "m"}, assignment=ASSIGNED)
    assert without.routes == ()
    assert [p.reason for p in without.passed] == ["no_key"]


ALL_KEYS: dict[str, str | None] = {"google": "g", "mistral": "m", "anthropic": "a", "openai": "o"}


def test_images_to_read_only_to_a_model_that_reads_them() -> None:
    routing = route(Needs(vision=True), own=None, keys=ALL_KEYS, assignment=ASSIGNED)
    assert all(r.profile.vision for r in routing.routes) and routing.routes
    blind = route(
        Needs(vision=True),
        own=None,
        keys=ALL_KEYS,
        assignment=Assignment(("mistral", "mistral-large-latest")),
    )
    assert ("mistral-large-latest", "vision") in {(p.model, p.reason) for p in blind.passed}


async def test_openai_is_asked_in_chat_completions_with_leka_s_key() -> None:
    request = Request(purpose="test", messages=[Message.user("Résume cet incident.")])
    answer = {
        "id": "o-1",
        "model": "gpt-4.1-2025-04-14",
        "choices": [
            {"message": {"role": "assistant", "content": "Résumé."}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
    done, sent = await _ask(OPENAI, _call("openai", "gpt-4.1", request), answer)
    assert done.text == "Résumé."
    assert str(sent.url) == "https://api.openai.com/v1/chat/completions"
    assert sent.headers["authorization"] == "Bearer key-1"
    assert json.loads(sent.content)["model"] == "gpt-4.1"


# ── GPT-6, in the Responses API ──────────────────────────────────────────────


def _response(*items: dict[str, Any], status: str = "completed", **extra: Any) -> dict[str, Any]:
    return {
        "id": "resp-1",
        "model": "gpt-6.1-sol-2026-09-30",
        "status": status,
        "output": list(items),
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens": 30,
            "output_tokens_details": {"reasoning_tokens": 20},
        },
        **extra,
    }


async def test_gpt_6_is_asked_in_the_responses_api_its_answer_as_json() -> None:
    # 2026-10-21: GPT-6 calls no tool in chat completions, only here.
    request = Request(
        purpose="test",
        messages=[Message.system("Be brief."), Message.user("Classify this.")],
        output=Output.of(Verdict),
        temperature=0.2,
    )
    answer = _response(
        {"type": "reasoning", "id": "rs_1", "encrypted_content": "e", "summary": []},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": '{"goal": "a", "confidence": 1}'}],
        },
    )
    done, sent = await _ask(OPENAI, _call("openai", "gpt-6.1-sol", request), answer)
    assert str(sent.url) == "https://api.openai.com/v1/responses"
    body = json.loads(sent.content)
    assert body["instructions"] == "Be brief."
    assert body["input"] == [{"role": "user", "content": "Classify this."}]
    assert body["store"] is False and "temperature" not in body
    assert body["text"]["format"]["type"] == "json_schema"
    assert json.loads(done.text) == {"goal": "a", "confidence": 1}
    assert (done.usage.tokens_in, done.usage.tokens_cached) == (100, 40)
    assert (done.usage.tokens_out, done.usage.tokens_thinking) == (30, 20)
    assert done.version == "gpt-6.1-sol-2026-09-30"

    # Cut at its limit: said as chat completions says it.
    cut = _response(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    done, _ = await _ask(OPENAI, _call("openai", "gpt-6.1-sol", request), cut)
    assert done.finish == "length"


async def test_gpt_6_s_reasoning_goes_back_whole_with_its_tool_calls() -> None:
    request = Request(
        purpose="test",
        messages=[Message.user("Who owns payment-api?")],
        tools=[LOOKUP],
        tool_choice=ToolChoice.REQUIRED,
    )
    thought = {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque", "summary": []}
    answer = _response(
        thought,
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"name": "payment-api"}',
        },
    )
    done, sent = await _ask(OPENAI, _call("openai", "gpt-6-luna", request), answer)
    body = json.loads(sent.content)
    assert body["tools"][0]["name"] == "lookup" and body["tool_choice"] == "required"
    assert done.tool_calls[0].id == "call_1"
    assert done.tool_calls[0].arguments == {"name": "payment-api"}

    follow = Request(
        purpose="test",
        messages=[
            Message.user("Who owns payment-api?"),
            Message(Role.ASSISTANT, "", tool_calls=done.tool_calls),
            Message(Role.TOOL, '{"owner": "Payments"}', tool_call_id="call_1", name="lookup"),
        ],
        tools=[LOOKUP],
    )
    _, sent = await _ask(OPENAI, _call("openai", "gpt-6-luna", follow), answer)
    items = json.loads(sent.content)["input"]
    assert items[1] == thought
    assert items[2]["type"] == "function_call" and items[2]["call_id"] == "call_1"
    assert items[3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"owner": "Payments"}',
    }

    # GPT-5.6 too: chat completions refuses its tools (400, checked live).
    _, sent = await _ask(OPENAI, _call("openai", "gpt-5.6-sol", request), answer)
    assert str(sent.url) == "https://api.openai.com/v1/responses"
    # GPT-4.1 stays in chat completions.
    _, sent = await _ask(
        OPENAI, _call("openai", "gpt-4.1", request), {"choices": [{"message": {}}]}
    )
    assert str(sent.url) == "https://api.openai.com/v1/chat/completions"


def test_a_step_its_own_model_cannot_do_goes_to_its_provider_s_strongest_on_its_key() -> None:
    # 2026-10-29: Mistral Medium chosen, a redesign written by it — twelve
    # tests red, no mock-up drawn. The hard steps (quality 3): Mistral Large,
    # on the workspace's own key; the rest stays with Medium.
    endpoint = Endpoint("mistral", "ws-key", owner="workspace")
    own = Own(endpoint, "mistral-medium-latest")
    hard = route(Needs(quality=3), own=own, keys=KEYS, assignment=ASSIGNED)
    assert _order(hard)[0] == ("mistral", "mistral-large-latest", "own_stronger")
    assert hard.routes[0].endpoint.api_key == "ws-key"
    easy = route(Needs(), own=own, keys=KEYS, assignment=ASSIGNED)
    assert _order(easy)[0] == ("mistral", "mistral-medium-latest", "own")
    # Ours only: still its provider's strongest, never LEKA's.
    only = route(
        Needs(quality=3),
        own=Own(endpoint, own.model, exclusive=True),
        keys=KEYS,
        assignment=ASSIGNED,
    )
    assert [r[2] for r in _order(only)] == ["own_stronger"]
