"""Google's Gemini API (LEKA-394) — LEKA's default provider for the MVP.

generateContent, stateless: the whole conversation each time. A structured
answer is asked with `responseJsonSchema`; tools are function declarations.
Gemini 3 thinks before it answers — how much is the tier (thinkingLevel) —
and signs the tool calls it makes: the signature goes back with the call on
the next turn, or the model refuses the conversation.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from leka.capabilities.gateway.contract import (
    Call,
    Completion,
    Message,
    ProviderError,
    Role,
    ToolCall,
    ToolChoice,
    Usage,
    arguments_of,
    failure,
    mapping,
)

LEVELS = {"fast": "low", "standard": "medium", "deep": "high"}
MODES = {ToolChoice.AUTO: "AUTO", ToolChoice.REQUIRED: "ANY", ToolChoice.NONE: "NONE"}


def _contents(messages: list[Message]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for message in messages:
        if message.role is Role.SYSTEM:
            continue
        if message.role is Role.TOOL:
            part = {
                "functionResponse": {
                    "name": message.name or "",
                    "id": message.tool_call_id,
                    "response": {"result": message.content},
                }
            }
            # The results of one turn's calls go back together.
            if (
                contents
                and contents[-1]["role"] == "user"
                and "functionResponse" in (contents[-1]["parts"][-1])
            ):
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
            continue
        if message.role is Role.ASSISTANT:
            parts: list[dict[str, Any]] = []
            if message.content:
                parts.append({"text": message.content})
            for tool_call in message.tool_calls:
                said: dict[str, Any] = {
                    "functionCall": {
                        "name": tool_call.name,
                        "args": dict(tool_call.arguments),
                        "id": tool_call.id,
                    }
                }
                if tool_call.signature:
                    said["thoughtSignature"] = tool_call.signature
                parts.append(said)
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            continue
        contents.append({"role": "user", "parts": [{"text": message.content}]})
    return contents


def body_of(call: Call) -> dict[str, Any]:
    request = call.request
    system = "\n\n".join(m.content for m in request.messages if m.role is Role.SYSTEM)
    config: dict[str, Any] = {"maxOutputTokens": request.max_tokens}
    if request.temperature is not None and call.sends_temperature:
        config["temperature"] = request.temperature
    level = LEVELS[request.tier.value]
    if call.thinking and level in call.thinking:
        config["thinkingConfig"] = {"thinkingLevel": level}
    if request.output is not None:
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = dict(request.output.schema)
    body: dict[str, Any] = {
        "contents": _contents(list(request.messages)),
        "generationConfig": config,
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if request.tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parametersJsonSchema": dict(tool.parameters),
                    }
                    for tool in request.tools
                ]
            }
        ]
        body["toolConfig"] = {"functionCallingConfig": {"mode": MODES[request.tool_choice]}}
    return body


def read(said: dict[str, Any], call: Call, latency_ms: int) -> Completion:
    feedback = said.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        raise ProviderError(f"Refused by the provider: {feedback['blockReason']}", retryable=False)
    candidates = said.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise ProviderError("No answer in the response.", retryable=True)
    candidate = candidates[0]
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    texts: list[str] = []
    calls: list[ToolCall] = []
    for index, part in enumerate(parts if isinstance(parts, list) else []):
        if not isinstance(part, dict) or part.get("thought"):
            continue
        function = part.get("functionCall")
        if isinstance(function, dict):
            calls.append(
                ToolCall(
                    id=str(function.get("id") or f"call_{index}"),
                    name=str(function.get("name") or ""),
                    arguments=arguments_of(function.get("args") or {}),
                    signature=part.get("thoughtSignature"),
                )
            )
        elif isinstance(part.get("text"), str):
            texts.append(part["text"])
    usage = mapping(said.get("usageMetadata"))
    thinking = int(usage.get("thoughtsTokenCount") or 0)
    return Completion(
        text="".join(texts),
        tool_calls=tuple(calls),
        provider="google",
        model=call.model,
        version=str(said.get("modelVersion") or call.model),
        usage=Usage(
            tokens_in=int(usage.get("promptTokenCount") or 0),
            # Thinking is billed as output.
            tokens_out=int(usage.get("candidatesTokenCount") or 0) + thinking,
            tokens_thinking=thinking,
            tokens_cached=int(usage.get("cachedContentTokenCount") or 0),
            reported=bool(usage),
        ),
        latency_ms=latency_ms,
        finish=candidate.get("finishReason"),
        request_id=said.get("responseId"),
    )


class Google:
    name = "google"
    title = "Google Gemini"
    default_url = "https://generativelanguage.googleapis.com/v1beta"
    needs = frozenset({"key"})

    async def complete(self, call: Call, client: httpx.AsyncClient) -> Completion:
        url = f"{call.endpoint.url(self.default_url)}/models/{call.model}:generateContent"
        headers = {"x-goog-api-key": call.endpoint.api_key or ""}
        started = time.monotonic()
        response = await client.post(url, json=body_of(call), headers=headers)
        if response.status_code >= 400:
            raise failure(response)
        said = response.json()
        if not isinstance(said, dict):
            raise ProviderError("The answer is not an object.", retryable=True)
        return read(said, call, int((time.monotonic() - started) * 1000))
