"""The chat-completions shape (LEKA-394): OpenAI's API, Mistral's — which
speaks it — a company's own Azure OpenAI, and any endpoint compatible with
it (a self-hosted model, a proxy).

    mistral        LEKA's fallback: in Europe
    openai         OpenAI, or any compatible endpoint (`base_url`)
    azure_openai   a company's own models, in its own tenant — what a
                   Microsoft 365 Copilot customer holds: Copilot itself is
                   no API a platform can call, its Azure OpenAI is

A structured answer is asked as a JSON schema (`response_format`), tools as
functions; a tool call's arguments come back as a JSON string.

GPT-6 calls tools only in OpenAI's Responses API: a model whose profile says
so is asked there instead (`responses`) — the same key, other words. Asked
statelessly (`store: false`): what it reasoned before its tool calls comes
back encrypted and goes back with them, whole.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
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

AZURE_API_VERSION = "2024-10-21"


def _message(message: Message) -> dict[str, Any]:
    if message.role is Role.TOOL:
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    if message.role is Role.ASSISTANT and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role.value, "content": message.content}


def _thoughts(signature: str | None) -> list[dict[str, Any]]:
    """The reasoning items kept as a tool call's signature — none from
    another provider's."""
    try:
        items = json.loads(signature or "")
    except ValueError:
        return []
    if not isinstance(items, list):
        return []
    return [i for i in items if isinstance(i, dict) and i.get("type") == "reasoning"]


def _items(messages: list[Message]) -> list[dict[str, Any]]:
    said: list[dict[str, Any]] = []
    for message in messages:
        if message.role is Role.SYSTEM:
            continue
        if message.role is Role.TOOL:
            said.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content,
                }
            )
            continue
        if message.role is Role.ASSISTANT and message.tool_calls:
            said.extend(_thoughts(message.tool_calls[0].signature))
            if message.content:
                said.append({"role": "assistant", "content": message.content})
            said.extend(
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                }
                for call in message.tool_calls
            )
            continue
        said.append({"role": message.role.value, "content": message.content})
    return said


def responses_body(call: Call) -> dict[str, Any]:
    """What the Responses API is asked."""
    request = call.request
    body: dict[str, Any] = {
        "model": call.model,
        "input": _items(list(request.messages)),
        "max_output_tokens": request.max_tokens,
        # Nothing kept at OpenAI; its reasoning comes back encrypted.
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    system = "\n\n".join(m.content for m in request.messages if m.role is Role.SYSTEM)
    if system:
        body["instructions"] = system
    if request.temperature is not None and call.sends_temperature:
        body["temperature"] = request.temperature
    if request.output is not None:
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": request.output.name,
                "schema": dict(request.output.schema),
                "strict": False,
            }
        }
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
                "strict": False,
            }
            for tool in request.tools
        ]
        body["tool_choice"] = request.tool_choice.value
    return body


def read_response(said: dict[str, Any], call: Call, latency_ms: int) -> Completion:
    """A Responses API answer, as the gateway reads any."""
    output = said.get("output")
    if not isinstance(output, list):
        raise ProviderError("No answer in the response.", retryable=True)
    texts: list[str] = []
    calls: list[ToolCall] = []
    thoughts: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "reasoning":
            thoughts.append(item)
        elif item.get("type") == "function_call":
            calls.append(
                ToolCall(
                    id=str(item.get("call_id") or item.get("id") or f"call_{len(calls)}"),
                    name=str(item.get("name") or ""),
                    arguments=arguments_of(item.get("arguments")),
                )
            )
        elif item.get("type") == "message":
            texts.extend(
                str(part.get("text") or "")
                for part in item.get("content") or []
                if isinstance(part, dict) and part.get("type") == "output_text"
            )
    if thoughts and calls:
        # Opaque to LEKA, sent back whole with the calls (_items).
        calls[0] = replace(calls[0], signature=json.dumps(thoughts))
    usage = mapping(said.get("usage"))
    details = mapping(usage.get("output_tokens_details"))
    cached = mapping(usage.get("input_tokens_details"))
    incomplete = mapping(said.get("incomplete_details"))
    return Completion(
        text="".join(texts),
        tool_calls=tuple(calls),
        provider=call.endpoint.provider,
        model=call.model,
        version=str(said.get("model") or call.model),
        usage=Usage(
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            tokens_thinking=int(details.get("reasoning_tokens") or 0),
            tokens_cached=int(cached.get("cached_tokens") or 0),
            reported=bool(usage),
        ),
        latency_ms=latency_ms,
        # Cut at max_output_tokens: « length », as chat completions says it.
        finish="length" if incomplete.get("reason") == "max_output_tokens" else said.get("status"),
        request_id=said.get("id"),
    )


class ChatCompletions:
    """One API shape, three providers: what differs is where it is, how the
    key is sent, and two words."""

    def __init__(
        self,
        name: str,
        title: str,
        default_url: str,
        needs: frozenset[str],
        *,
        max_tokens_field: str = "max_tokens",
        required_word: str = "required",
    ) -> None:
        self.name = name
        self.title = title
        self.default_url = default_url
        self.needs = needs
        self._max_tokens_field = max_tokens_field
        self._required_word = required_word

    def body_of(self, call: Call) -> dict[str, Any]:
        request = call.request
        body: dict[str, Any] = {
            "messages": [_message(m) for m in request.messages],
            self._max_tokens_field: request.max_tokens,
        }
        if self.name != "azure_openai":
            body["model"] = call.model
        if request.temperature is not None and call.sends_temperature:
            body["temperature"] = request.temperature
        if request.output is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.output.name,
                    "schema": dict(request.output.schema),
                    "strict": False,
                },
            }
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": dict(tool.parameters),
                    },
                }
                for tool in request.tools
            ]
            body["tool_choice"] = (
                self._required_word
                if request.tool_choice is ToolChoice.REQUIRED
                else request.tool_choice.value
            )
        return body

    def _where(self, call: Call) -> tuple[str, dict[str, str]]:
        endpoint = call.endpoint
        if self.name == "azure_openai":
            version = endpoint.api_version or AZURE_API_VERSION
            url = (
                f"{endpoint.url(self.default_url)}/openai/deployments/{call.model}"
                f"/chat/completions?api-version={version}"
            )
            return url, {"api-key": endpoint.api_key or ""}
        headers = {"authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}
        return f"{endpoint.url(self.default_url)}/chat/completions", headers

    def read(self, said: dict[str, Any], call: Call, latency_ms: int) -> Completion:
        choices = said.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError("No answer in the response.", retryable=True)
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ProviderError("No message in the answer.", retryable=True)
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        calls = tuple(
            ToolCall(
                id=str(raw.get("id") or f"call_{index}"),
                name=str(mapping(raw.get("function")).get("name") or ""),
                arguments=arguments_of(mapping(raw.get("function")).get("arguments")),
            )
            for index, raw in enumerate(message.get("tool_calls") or [])
            if isinstance(raw, dict)
        )
        usage = mapping(said.get("usage"))
        details = usage.get("completion_tokens_details")
        thinking = int(details.get("reasoning_tokens") or 0) if isinstance(details, dict) else 0
        prompt = usage.get("prompt_tokens_details")
        cached = int(prompt.get("cached_tokens") or 0) if isinstance(prompt, dict) else 0
        return Completion(
            text=text,
            tool_calls=calls,
            provider=self.name,
            model=call.model,
            version=str(said.get("model") or call.model),
            usage=Usage(
                tokens_in=int(usage.get("prompt_tokens") or 0),
                tokens_out=int(usage.get("completion_tokens") or 0),
                tokens_thinking=thinking,
                tokens_cached=cached,
                reported=bool(usage),
            ),
            latency_ms=latency_ms,
            finish=choice.get("finish_reason"),
            request_id=said.get("id"),
        )

    async def complete(self, call: Call, client: httpx.AsyncClient) -> Completion:
        url, headers = self._where(call)
        if not url.startswith("http"):
            raise ProviderError("No address for this provider.", retryable=False)
        started = time.monotonic()
        if call.responses:
            url = url.removesuffix("/chat/completions") + "/responses"
            response = await client.post(url, json=responses_body(call), headers=headers)
            if response.status_code >= 400:
                raise failure(response)
            answered = response.json()
            if not isinstance(answered, dict):
                raise ProviderError("The answer is not an object.", retryable=True)
            return read_response(answered, call, int((time.monotonic() - started) * 1000))
        response = await client.post(url, json=self.body_of(call), headers=headers)
        if response.status_code >= 400:
            raise failure(response)
        said = response.json()
        if not isinstance(said, dict):
            raise ProviderError("The answer is not an object.", retryable=True)
        return self.read(said, call, int((time.monotonic() - started) * 1000))


MISTRAL = ChatCompletions(
    "mistral",
    "Mistral AI",
    "https://api.mistral.ai/v1",
    frozenset({"key"}),
    # Mistral says "any" for a call it must make.
    required_word="any",
)
OPENAI = ChatCompletions(
    "openai",
    "OpenAI (ou compatible)",
    "https://api.openai.com/v1",
    frozenset({"key", "model"}),
    max_tokens_field="max_completion_tokens",
)
AZURE_OPENAI = ChatCompletions(
    "azure_openai",
    "Azure OpenAI",
    "",
    frozenset({"key", "url", "model"}),
)
