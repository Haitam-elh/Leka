"""Anthropic's Messages API (LEKA-394).

The system prompt apart from the conversation; tool calls are content
blocks (`tool_use`), their results go back as `tool_result` blocks in a user
turn. A structured answer is asked the way that holds on every Claude model:
as the one tool the model must call, the schema its input — what it passes
is the answer.
"""

from __future__ import annotations

import json
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

VERSION = "2023-06-01"


def _messages(messages: list[Message]) -> list[dict[str, Any]]:
    said: list[dict[str, Any]] = []
    for message in messages:
        if message.role is Role.SYSTEM:
            continue
        if message.role is Role.TOOL:
            block = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content,
            }
            last = said[-1] if said else None
            if (
                last is not None
                and last["role"] == "user"
                and isinstance(last["content"], list)
                and last["content"]
                and last["content"][-1].get("type") == "tool_result"
            ):
                last["content"].append(block)
            else:
                said.append({"role": "user", "content": [block]})
            continue
        if message.role is Role.ASSISTANT and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {"type": "tool_use", "id": c.id, "name": c.name, "input": dict(c.arguments)}
                for c in message.tool_calls
            )
            said.append({"role": "assistant", "content": blocks})
            continue
        said.append({"role": message.role.value, "content": message.content})
    return said


class Anthropic:
    name = "anthropic"
    title = "Anthropic Claude"
    default_url = "https://api.anthropic.com/v1"
    needs = frozenset({"key"})

    def body_of(self, call: Call) -> dict[str, Any]:
        request = call.request
        system = "\n\n".join(m.content for m in request.messages if m.role is Role.SYSTEM)
        body: dict[str, Any] = {
            "model": call.model,
            "max_tokens": request.max_tokens,
            "messages": _messages(list(request.messages)),
        }
        if system:
            body["system"] = system
        if request.temperature is not None and call.sends_temperature:
            body["temperature"] = request.temperature
        tools = [
            {"name": t.name, "description": t.description, "input_schema": dict(t.parameters)}
            for t in request.tools
        ]
        if request.output is not None:
            tools.append(
                {
                    "name": request.output.name,
                    "description": "Give the answer, in this shape.",
                    "input_schema": dict(request.output.schema),
                }
            )
            body["tool_choice"] = {"type": "tool", "name": request.output.name}
        elif request.tools:
            body["tool_choice"] = {
                ToolChoice.AUTO: {"type": "auto"},
                ToolChoice.REQUIRED: {"type": "any"},
                ToolChoice.NONE: {"type": "none"},
            }[request.tool_choice]
        if tools:
            body["tools"] = tools
        return body

    def read(self, said: dict[str, Any], call: Call, latency_ms: int) -> Completion:
        content = said.get("content")
        if not isinstance(content, list):
            raise ProviderError("No answer in the response.", retryable=True)
        output = call.request.output
        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                arguments = arguments_of(block.get("input") or {})
                if output is not None and block.get("name") == output.name:
                    # The structured answer: what it passed is the text.
                    texts = [json.dumps(arguments)]
                    continue
                calls.append(
                    ToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments=arguments,
                    )
                )
        usage = mapping(said.get("usage"))
        return Completion(
            text="".join(texts),
            tool_calls=tuple(calls),
            provider=self.name,
            model=call.model,
            version=str(said.get("model") or call.model),
            # What it read from its cache comes apart from input_tokens.
            usage=Usage(
                tokens_in=int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read_input_tokens") or 0),
                tokens_out=int(usage.get("output_tokens") or 0),
                tokens_cached=int(usage.get("cache_read_input_tokens") or 0),
            ),
            latency_ms=latency_ms,
            finish=said.get("stop_reason"),
            request_id=said.get("id"),
        )

    async def complete(self, call: Call, client: httpx.AsyncClient) -> Completion:
        url = f"{call.endpoint.url(self.default_url)}/messages"
        headers = {"x-api-key": call.endpoint.api_key or "", "anthropic-version": VERSION}
        started = time.monotonic()
        response = await client.post(url, json=self.body_of(call), headers=headers)
        if response.status_code >= 400:
            raise failure(response)
        said = response.json()
        if not isinstance(said, dict):
            raise ProviderError("The answer is not an object.", retryable=True)
        return self.read(said, call, int((time.monotonic() - started) * 1000))
