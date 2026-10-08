"""The contract every model provider meets (LEKA-394): a conversation in,
a completion out — whatever the vendor.

    Request     what a LEKA feature asks: its messages, how much it asks
                (tier), the shape of what it wants back (a JSON schema),
                the tools it offers the model
    Completion  what came back: the text, or the tools the model wants
                called; who answered — provider, model, the version it said
                — the tokens, how long it took
    Provider    one vendor's way of saying both, over plain HTTP: what a
                new provider implements, then registers — nothing else in
                LEKA changes

A feature never names a provider or a model: it says what it needs
(routing.py), the gateway (service.py) picks.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel


class Tier(enum.StrEnum):
    """How much a task asks of a model — how long it may think."""

    FAST = "fast"  # understanding, routing, classifying: quick and cheap
    STANDARD = "standard"  # an analysis written, an answer grounded
    DEEP = "deep"  # an agent's long work


class Role(enum.StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"  # what a tool returned, for the call it answers


@dataclass(frozen=True)
class ToolCall:
    """A tool the model wants called, with what."""

    id: str
    name: str
    arguments: Mapping[str, Any]
    # What the provider needs back with it on the next turn (a Gemini
    # thought signature); opaque to everyone else.
    signature: str | None = None


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    # An assistant turn that called tools.
    tool_calls: tuple[ToolCall, ...] = ()
    # A tool turn: the call it answers, and the tool's name.
    tool_call_id: str | None = None
    name: str | None = None

    @classmethod
    def system(cls, content: str) -> Message:
        return cls(Role.SYSTEM, content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(Role.USER, content)


@dataclass(frozen=True)
class Tool:
    """A function the model may ask to be called: its parameters, a JSON
    schema."""

    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class Output:
    """The shape of the answer wanted: a JSON object matching `schema`."""

    name: str
    schema: Mapping[str, Any]

    @classmethod
    def of(cls, model: type[BaseModel]) -> Output:
        return cls(name=model.__name__, schema=plain_schema(model))


class ToolChoice(enum.StrEnum):
    AUTO = "auto"  # the model decides
    REQUIRED = "required"  # it must call one
    NONE = "none"  # it may not


@dataclass(frozen=True)
class Request:
    """What a LEKA feature asks a model."""

    # What it is for — "intention.understanding", "capability.synthesis",
    # "agent:<key>": what usage and audit read.
    purpose: str
    messages: Sequence[Message]
    tier: Tier = Tier.STANDARD
    max_tokens: int = 2000
    # None: the model's own (Gemini 3 asks to be left at its default).
    temperature: float | None = None
    output: Output | None = None
    tools: Sequence[Tool] = ()
    tool_choice: ToolChoice = ToolChoice.AUTO
    # What it is about — an intention, a capability run: kept with each call.
    ref: str | None = None


@dataclass(frozen=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    # Thinking a provider bills as output, said apart where it says it.
    tokens_thinking: int = 0


@dataclass(frozen=True)
class Completion:
    text: str
    tool_calls: tuple[ToolCall, ...]
    provider: str
    model: str
    # The version the provider said answered (Gemini's modelVersion, the
    # dated model behind a "-latest" alias); the model asked, when it says
    # none.
    version: str
    usage: Usage
    latency_ms: int
    finish: str | None = None
    request_id: str | None = None


class ProviderError(Exception):
    """A model did not answer usably. `retryable`: it, or another, may."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class Endpoint:
    """One provider as configured: LEKA's own, or a workspace's."""

    provider: str
    api_key: str | None
    base_url: str | None = None
    # Azure OpenAI: the API version its resource speaks.
    api_version: str | None = None
    # leka, or workspace: whose account pays, whose contract applies.
    owner: str = "leka"

    def url(self, default: str) -> str:
        return (self.base_url or default).rstrip("/")


@dataclass(frozen=True)
class Call:
    """One call to one model, as a provider is handed it."""

    endpoint: Endpoint
    model: str
    request: Request
    # The model's profile (profiles.py): what it accepts.
    thinking: tuple[str, ...] = ()
    sends_temperature: bool = True


class Provider(Protocol):
    """A vendor, as LEKA speaks to it — implemented once per API shape."""

    name: str
    title: str
    # Where its API is when the endpoint says nowhere; "" when it must say.
    default_url: str
    # What a workspace bringing its own must give: key, url, api_version,
    # model.
    needs: frozenset[str]

    async def complete(self, call: Call, client: httpx.AsyncClient) -> Completion: ...


_PROVIDERS: dict[str, Provider] = {}


def register_provider(provider: Provider) -> None:
    """A provider LEKA can call. Registering one is all a new vendor takes."""
    _PROVIDERS[provider.name] = provider


def provider(name: str) -> Provider | None:
    return _PROVIDERS.get(name)


def providers() -> list[Provider]:
    return list(_PROVIDERS.values())


# ── shared by the providers ─────────────────────────────────────────────────

RETRYABLE = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})


def failure(response: httpx.Response) -> ProviderError:
    """An HTTP refusal, said: retryable when the provider says it is
    temporary, with how long it asks to wait."""
    status = response.status_code
    try:
        said = response.json()
        detail = said.get("error", said) if isinstance(said, dict) else said
        if isinstance(detail, dict):
            detail = detail.get("message") or detail
        text = str(detail)[:300]
    except ValueError:
        text = response.text[:300]
    wait: float | None = None
    header = response.headers.get("retry-after")
    if header:
        try:
            wait = float(header)
        except ValueError:
            wait = None
    return ProviderError(
        f"{status}: {text}", status=status, retryable=status in RETRYABLE, retry_after=wait
    )


def mapping(value: object) -> dict[str, Any]:
    """A part of an answer that should be an object — empty when it is not."""
    return value if isinstance(value, dict) else {}


def arguments_of(raw: object) -> dict[str, Any]:
    """A tool call's arguments — a JSON string or an object — as an object."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
        except ValueError as error:
            raise ProviderError("A tool call's arguments are not JSON.", retryable=True) from error
        if isinstance(parsed, dict):
            return parsed
    raise ProviderError("A tool call's arguments are not an object.", retryable=True)


def plain_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A model's JSON schema, its references inlined: every provider reads
    that, not all of them read `$ref`."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(node: Any, seen: frozenset[str] = frozenset()) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name in seen:
                    msg = f"{model.__name__}: a recursive schema ({name}) cannot be inlined"
                    raise ValueError(msg)
                return inline(definitions[name], seen | {name})
            return {k: inline(v, seen) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [inline(item, seen) for item in node]
        return node

    inlined: dict[str, Any] = inline(schema)
    return inlined


@dataclass(frozen=True)
class Structured[T: BaseModel]:
    """A structured answer, read and checked against its model."""

    value: T
    completion: Completion
