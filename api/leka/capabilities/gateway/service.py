"""The model gateway (LEKA-394): the only place LEKA calls a language model
(architecture rule 7) — for Intentions, Mon environnement, Capacités, the
agents, the skills and the workflows alike.

    a feature asks (Request) and says what it needs (Needs)
      ──▶ routing.py: the models that can answer, in order
      ──▶ each tried: a temporary failure tried again (LEKA_LLM_RETRIES),
          then the next model — never more than three
      ──▶ a structured answer read and checked against its model: one that
          does not match is tried again, then the next model
      ──▶ every attempt kept (model_calls): for what, about what, which
          provider, model and version, its tokens — or that the provider
          did not say them — its cost at the rate in force (rates.py, the
          rate kept with it), how long — or why it failed

A workspace's model is its company's: its account, its contract, its data
residency, and what it costs LEKA nothing. A failed one falls back to
LEKA's, said in the record — unless the workspace said "ours only". One
refusing its key is marked failed, for its admin to see. What no model can
answer raises NoModelError: nothing is made up, and the caller says so or
does without.

A workspace's address (its Azure resource, its own endpoint) is reached
through the connectors' transport — public https only, pinned against DNS
rebinding — as any customer-given address is.

The workspace's AI controls (LEKA-406, controls.py) stand on both sides:
before, the models this work may use and its usage limits; after, what the
answer may not carry. What they refuse raises NoModelError, said why
(refused, limited, blocked) — and each call says whom it was for.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.gateway.contract import (
    Call,
    Completion,
    Endpoint,
    Message,
    Output,
    ProviderError,
    Request,
    Role,
    Structured,
    Tier,
    ToolChoice,
    provider,
)
from leka.capabilities.gateway.controls import ControlRefusedError, Guard
from leka.capabilities.gateway.profiles import DEFAULTS
from leka.capabilities.gateway.rates import Rates, load_rates
from leka.capabilities.gateway.routing import (
    Needs,
    Own,
    Passed,
    Route,
    Routing,
    fallbacks_of,
    task_routes_of,
)
from leka.capabilities.gateway.routing import route as route_of
from leka.capabilities.models import ModelCall, WorkspaceModel, WorkspaceModelDefault
from leka.connectors import BlockedAddressError, PublicTransport
from leka.core import breaker
from leka.core.config import settings
from leka.governance import current_actor
from leka.platform import DecryptionError, secret_box

logger = structlog.get_logger(__name__)

TIMEOUTS = {Tier.FAST: 30.0, Tier.STANDARD: 90.0, Tier.DEEP: 300.0}
# A long answer takes longer to write: past its tier's wait, a second for
# every TOKENS_A_SECOND tokens it may hold (2026-10-27: a whole page's
# change, answered whole, was cut at 300 s — twice).
TOKENS_A_SECOND = 60
# Models tried for one request, at most: past three, the failure is not
# the model's.
MOST_MODELS = 3
LONGEST_WAIT = 10.0


def wait_of(request: Request) -> float:
    """How long a model is waited for, `request` its answer's size."""
    return max(TIMEOUTS[request.tier], request.max_tokens / TOKENS_A_SECOND)


Sleep = Callable[[float], Awaitable[None]]
ToolHandler = Callable[[Mapping[str, Any]], Awaitable[str]]


class NoModelError(Exception):
    """No model is configured that can do it, or none answered — said why:
    `reason` none (no model can), unanswered (every one tried failed),
    timeout (the budget was spent), tools (too many rounds of tools); an AI
    control's (LEKA-406): refused (no model allowed), limited (a usage
    limit reached), blocked (what the answer carried)."""

    def __init__(
        self,
        message: str,
        attempts: Sequence[Attempt] = (),
        passed: Sequence[Passed] = (),
        *,
        reason: str = "unanswered",
    ) -> None:
        super().__init__(message)
        self.attempts = list(attempts)
        self.passed = list(passed)
        self.reason = reason


# What a concluding model is given of what its tools returned, at most.
READ_KEPT = 12_000
READ_TOTAL = 400_000
CONCLUDE = (
    "You have used every round of tools this run allows. Answer now, as your "
    "instructions ask, with only what you read below — no tool any more; say "
    "what is missing.\n\nWhat you read, in order:\n"
)


def _what_was_read(exchanged: Sequence[Message]) -> str:
    """Each tool call made and what it returned, as text."""
    asked: dict[str, str] = {}
    parts = [CONCLUDE]
    size = len(CONCLUDE)
    for message in exchanged:
        for call in message.tool_calls:
            arguments = json.dumps(dict(call.arguments), ensure_ascii=False, default=str)
            asked[call.id] = f"{call.name} {arguments}"
        if message.role is Role.TOOL:
            said = f"\n## {asked.get(message.tool_call_id or '', message.name or 'tool')}\n"
            said += message.content[:READ_KEPT]
            if size + len(said) > READ_TOTAL:
                parts.append("\n(the rest is left out: too long)")
                break
            parts.append(said)
            size += len(said)
    return "".join(parts)


class ToolRoundsError(NoModelError):
    """A model that kept asking for tools and never answered (run_tools)."""


class InvalidOutputError(Exception):
    """A structured answer that does not match what was asked."""


class CutOutputError(InvalidOutputError):
    """An answer cut at its token limit: asked again as it is, it would be
    cut again — told once, never `corrections` times."""


@dataclass(frozen=True)
class Attempt:
    provider: str
    model: str
    owner: str
    route: str
    attempt: int
    error: str


@dataclass(frozen=True)
class Tested:
    ok: bool
    detail: str | None
    latency_ms: int | None
    model: str | None
    version: str | None


def leka_keys() -> dict[str, str | None]:
    """The keys LEKA holds, by provider."""
    keys = {
        "google": settings.google_api_key,
        "mistral": settings.mistral_api_key,
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
    }
    return {name: key.get_secret_value() if key else None for name, key in keys.items()}


def leka_urls() -> dict[str, str]:
    """Where LEKA's default model is reached, when not its provider's own
    address: a proxy, a regional endpoint — or, in the browser tests, a
    local stand-in (LEKA_LLM_API_URL)."""
    return {settings.llm_provider: settings.llm_api_url} if settings.llm_api_url else {}


def leka_default() -> tuple[str, str]:
    """LEKA's default model: configured, never written where it is used."""
    return settings.llm_provider, settings.llm_model


def default_ready() -> bool:
    """Whether LEKA's default model can be reached at all."""
    return settings.llm_api_key is not None


def own_of(row: WorkspaceModel) -> Own | None:
    """A workspace's model as routing sees it — none when it is off, or its
    key cannot be read."""
    if not row.enabled:
        return None
    key: str | None = None
    if row.key_ciphertext:
        try:
            key = secret_box.decrypt(row.key_ciphertext)
        except DecryptionError:
            logger.error("workspace_model_key_unreadable", workspace=str(row.workspace_id))
            return None
    model = row.model or DEFAULTS.get(row.provider)
    if not model:
        return None
    endpoint = Endpoint(
        provider=row.provider,
        api_key=key,
        base_url=row.base_url,
        api_version=row.api_version,
        owner="workspace",
    )
    return Own(endpoint, model, exclusive=row.exclusive)


# How a provider says an answer stopped at its token limit.
CUT = frozenset({"MAX_TOKENS", "LENGTH"})


def corrected(request: Request, done: Completion, invalid: str) -> Request:
    """The request again, with the answer given and why it is not used."""
    return replace(
        request,
        messages=[
            *request.messages,
            Message(Role.ASSISTANT, done.text),
            Message.user(
                f"{invalid} Answer again, as asked: the whole answer, corrected — "
                "and only the answer."
            ),
        ],
    )


def json_of(text: str) -> str:
    """The JSON in an answer — some models fence it all the same."""
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", text, re.DOTALL)
    return fenced.group(1) if fenced else text.strip()


# The words a JSON schema frames itself with — and the request's own
# wrapper around it: an answer given inside them is that frame around the
# answer, not the answer.
_FRAME = frozenset(
    {
        "$schema",
        "$defs",
        "definitions",
        "type",
        "description",
        "properties",
        "required",
        "additionalProperties",
        "name",
        "schema",
        "json_schema",
        "strict",
    }
)
# What describes one field in a schema: a field given as such holds its
# value in `default`, `value` or `example` — or, a list, in `items`.
_NODE = frozenset(
    {
        "type",
        "description",
        "title",
        "default",
        "value",
        "example",
        "examples",
        "items",
        "enum",
        "format",
        "anyOf",
        "$ref",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }
)


def _valued(node: Any) -> Any:
    if not isinstance(node, dict) or not node or not set(node) <= _NODE:
        return node
    for key in ("value", "default", "example"):
        if key in node:
            return node[key]
    items = node.get("items")
    return items if isinstance(items, list) else node


def unframed(text: str) -> list[str]:
    """The answer some models give inside the schema's own frame, taken out
    of it (2026-10-28: Mistral, nearly every time, each answer refused):
    its fields beside the frame, {"properties": {the answer}}, or each field
    as the schema describes it with its value in it — every reading that
    may be it, the likeliest first; none when it is not so framed."""
    try:
        said = json.loads(text)
    except ValueError:
        return []
    for _ in range(3):
        if not isinstance(said, dict) or "properties" in said or not set(said) <= _FRAME:
            break
        said = said.get("schema") or said.get("json_schema")
    if not isinstance(said, dict) or not isinstance(said.get("properties"), dict):
        return []
    beside = {k: v for k, v in said.items() if k not in _FRAME}
    inside = said["properties"]
    valued = {k: _valued(v) for k, v in inside.items()}
    readings = [{**valued, **beside}, inside, valued, beside]
    seen: list[str] = []
    for reading in readings:
        if reading:
            dumped = json.dumps(reading, ensure_ascii=False)
            if dumped not in seen:
                seen.append(dumped)
    return seen


class Gateway:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        keys: dict[str, str | None] | None = None,
        default: tuple[str, str] | None = None,
        fallbacks: Sequence[tuple[str, str]] | None = None,
        retries: int | None = None,
        sleep: Sleep = asyncio.sleep,
        urls: dict[str, str] | None = None,
    ) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._transport = transport
        self._keys = keys if keys is not None else leka_keys()
        self._default = default or leka_default()
        self._fallbacks = (
            list(fallbacks) if fallbacks is not None else fallbacks_of(settings.llm_fallbacks)
        )
        self._retries = max(0, settings.llm_retries if retries is None else retries)
        # How many times a model is told what was wrong with its answer and
        # asked again, before the next one is (structured `corrections`).
        self._corrections: int | None = None
        self._tasks = task_routes_of(settings.llm_task_routes)
        self._sleep = sleep
        self._urls = urls if urls is not None else (leka_urls() if keys is None else {})
        self._guard = Guard(session, workspace_id)
        self._rates: Rates | None = None

    # ── which model ─────────────────────────────────────────────────────────

    async def setting(self) -> WorkspaceModel | None:
        found: WorkspaceModel | None = await self._session.scalar(
            select(WorkspaceModel).where(WorkspaceModel.workspace_id == self._workspace_id)
        )
        return found

    async def chosen(self) -> WorkspaceModelDefault | None:
        """Which of LEKA's models its admin chose to answer first here."""
        found: WorkspaceModelDefault | None = await self._session.scalar(
            select(WorkspaceModelDefault).where(
                WorkspaceModelDefault.workspace_id == self._workspace_id
            )
        )
        return found

    async def defaults(self) -> tuple[tuple[str, str], list[tuple[str, str]]]:
        """LEKA's model that answers first here, and those after it: the one
        its admin chose — when LEKA holds its key — then LEKA's own default,
        then its fallbacks; LEKA's default otherwise (2026-10-21)."""
        chosen = await self.chosen()
        if chosen is None or not self._keys.get(chosen.provider):
            return self._default, self._fallbacks
        first = (chosen.provider, chosen.model)
        if first == self._default:
            return self._default, self._fallbacks
        return first, [self._default, *(f for f in self._fallbacks if f != first)]

    async def routing(self, needs: Needs = Needs()) -> Routing:
        row = await self.setting()
        default, fallbacks = await self.defaults()
        return route_of(
            needs,
            own=own_of(row) if row is not None else None,
            keys=self._keys,
            default=default,
            fallbacks=fallbacks,
            urls=self._urls,
            tasks=self._tasks,
        )

    async def ready(self, needs: Needs = Needs()) -> bool:
        """Whether a model can answer what is needed, here."""
        return bool((await self.routing(needs)).routes)

    def _client(self, endpoint: Endpoint, wait: float) -> httpx.AsyncClient:
        transport = self._transport
        if transport is None and endpoint.owner == "workspace":
            # A customer-given address: public https only.
            transport = PublicTransport()
        return httpx.AsyncClient(transport=transport, timeout=wait)

    # ── asking ──────────────────────────────────────────────────────────────

    async def complete(
        self,
        request: Request,
        needs: Needs = Needs(),
        *,
        budget: float | None = None,
        check: Callable[[Completion], None] | None = None,
    ) -> Completion:
        """The first model that answers what is asked — every attempt kept.
        `budget`: seconds for all of it, after which NoModelError."""
        if request.output is not None:
            needs = replace(needs, structured=True)
        if request.tools:
            needs = replace(needs, tools=True)
        routing = await self.routing(needs)
        if not routing.routes:
            reason = (
                "No language model is configured."
                if not any(self._keys.values()) and (await self.setting()) is None
                else "No configured model can do what is asked."
            )
            raise NoModelError(reason, passed=routing.passed, reason="none")
        try:
            routing = await self._guard.before(request, routing)
        except ControlRefusedError as refused:
            raise NoModelError(str(refused), passed=routing.passed, reason=refused.reason) from None
        work = self._through(request, routing, check)
        if budget is None:
            done = await work
        else:
            try:
                done = await asyncio.wait_for(work, timeout=budget)
            except TimeoutError as error:
                await self._session.flush()
                raise NoModelError(
                    "No answer in time.", passed=routing.passed, reason="timeout"
                ) from error
        try:
            return await self._guard.after(request, done)
        except ControlRefusedError as refused:
            raise NoModelError(str(refused), passed=routing.passed, reason=refused.reason) from None

    async def _through(
        self,
        request: Request,
        routing: Routing,
        check: Callable[[Completion], None] | None,
    ) -> Completion:
        attempts: list[Attempt] = []
        for route in routing.routes[:MOST_MODELS]:
            done = await self._one(request, route, check, attempts)
            if done is not None:
                await self._session.flush()
                return done
        await self._session.flush()
        raise NoModelError("No language model answered.", attempts, routing.passed)

    async def _one(
        self,
        request: Request,
        route: Route,
        check: Callable[[Completion], None] | None,
        attempts: list[Attempt],
    ) -> Completion | None:
        """One model, tried again while it says its failure is temporary."""
        vendor = provider(route.endpoint.provider)
        model = route.profile.model
        if self._rates is None:
            self._rates = await load_rates(self._session)
        if vendor is None:
            attempts.append(self._attempt(route, 1, "unknown provider"))
            return None
        # A provider failing for everyone is left alone a while: the next
        # route answers instead (LEKA-408).
        circuit = self._circuit(route)
        if not await breaker.allow(circuit):
            attempts.append(self._attempt(route, 1, "circuit open"))
            logger.warning("model_route_skipped", provider=route.endpoint.provider, why="circuit")
            return None
        call = Call(
            route.endpoint,
            model,
            # Never more than the model gives back: a request sized for the
            # largest one still reaches a smaller one (2026-10-18).
            replace(request, max_tokens=min(request.max_tokens, route.profile.output))
            if route.profile.output
            else request,
            thinking=route.profile.thinking,
            sends_temperature=route.profile.sends_temperature,
            forces_tools=route.profile.forces_tools,
            responses=route.profile.responses,
        )
        corrections = self._retries if self._corrections is None else self._corrections
        for attempt in range(1, max(self._retries, corrections) + 2):
            try:
                async with self._client(route.endpoint, wait_of(call.request)) as client:
                    done = await vendor.complete(call, client)
                if not done.text.strip() and not done.tool_calls and not request.empty_ok:
                    raise ProviderError("An empty answer.", retryable=True)
            except (ProviderError, httpx.HTTPError) as raised:
                error = _said(raised)
                self._record(request, route, attempt, error=str(error), status="failed")
                attempts.append(self._attempt(route, attempt, str(error)))
                logger.warning(
                    "model_call_failed",
                    purpose=request.purpose,
                    provider=route.endpoint.provider,
                    model=model,
                    owner=route.endpoint.owner,
                    status=error.status,
                    attempt=attempt,
                )
                if error.retryable and attempt <= self._retries:
                    await self._sleep(min(error.retry_after or 2.0 ** (attempt - 1), LONGEST_WAIT))
                    continue
                if route.endpoint.owner == "workspace" and not error.retryable:
                    await self._mark(failed=str(error))
                if _down(raised, error):
                    # Once per request, its retries spent: the provider's
                    # failure, not the request's (LEKA-408).
                    await breaker.failure(circuit)
                return None
            if check is not None:
                try:
                    check(done)
                except InvalidOutputError as invalid:
                    # Answered, and billed: kept with its tokens.
                    self._record(
                        request, route, attempt, done=done, error=str(invalid), status="invalid"
                    )
                    attempts.append(self._attempt(route, attempt, str(invalid)))
                    told = self._retries if isinstance(invalid, CutOutputError) else corrections
                    if attempt <= told:
                        # Asked again with what was wrong — its own answer,
                        # and why it is not used — never the same words
                        # again: a model told corrects itself (2026-10-21:
                        # asked the same, it answered the same).
                        call = replace(call, request=corrected(call.request, done, str(invalid)))
                        continue
                    return None
            self._record(request, route, attempt, done=done, status="ok")
            await breaker.success(circuit)
            return done
        return None

    def _circuit(self, route: Route) -> str:
        """One breaker per provider and account: LEKA's key is shared by every
        workspace; a workspace's own, by it alone."""
        owner = route.endpoint.owner
        mine = f":{self._workspace_id}" if owner == "workspace" else ""
        return f"model:{route.endpoint.provider}:{owner}{mine}"

    @staticmethod
    def _attempt(route: Route, attempt: int, error: str) -> Attempt:
        return Attempt(
            route.endpoint.provider,
            route.profile.model,
            route.endpoint.owner,
            route.why,
            attempt,
            error,
        )

    async def structured[T: BaseModel](
        self,
        request: Request,
        model: type[T],
        needs: Needs = Needs(),
        *,
        budget: float | None = None,
        verify: Callable[[T], Sequence[str]] | None = None,
        corrections: int | None = None,
    ) -> Structured[T]:
        """An answer in the shape of `model`, checked — and, given `verify`,
        held to what the caller expects of it (what it cites is known…): one
        that does not match is asked again, then of the next model.
        `corrections`: how many times each model is told what was wrong and
        asked again — LEKA_LLM_RETRIES unless said (2026-10-29: a code change
        told once, then given up on, while each answer came closer)."""
        read: dict[str, Any] = {}

        def invalid(error: ValidationError, done: Completion) -> InvalidOutputError:
            # Cut at its token limit, thinking included: said as such,
            # never as a wrong shape (2026-10-18).
            if str(done.finish or "").upper() in CUT:
                return CutOutputError(
                    f"Cut at its limit of {request.max_tokens} tokens, thinking included."
                )
            errors = error.errors()
            where = ".".join(str(p) for p in errors[0]["loc"]) if errors else ""
            said = errors[0]["msg"] if errors else "invalid"
            return InvalidOutputError(f"Not the shape asked ({where or 'answer'}: {said}).")

        def check(done: Completion) -> None:
            text = json_of(done.text)
            value: T | None = None
            try:
                value = model.model_validate_json(text)
            except ValidationError as error:
                # Given inside the schema's own frame: the answer within.
                for reading in unframed(text):
                    try:
                        value = model.model_validate_json(reading)
                        break
                    except ValidationError:
                        continue
                if value is None:
                    raise invalid(error, done) from error
            problems = list(verify(value)) if verify is not None else []
            if problems:
                # Every problem said, so each is corrected at once.
                raise InvalidOutputError(f"Not what was asked: {'; '.join(problems)[:2000]}")
            read["value"] = value
            read["text"] = done.text

        held, self._corrections = self._corrections, corrections
        try:
            done = await self.complete(
                replace(request, output=Output.of(model)), needs, budget=budget, check=check
            )
        finally:
            self._corrections = held
        if done.text == read["text"]:
            return Structured(read["value"], done)
        # Redacted by an AI control (LEKA-406): read and held to what the
        # caller expects again, as it now is.
        try:
            check(done)
        except InvalidOutputError as error:
            raise NoModelError(
                "The answer, redacted, is no longer what was asked.", reason="blocked"
            ) from error
        return Structured(read["value"], done)

    async def run_tools(
        self,
        request: Request,
        handlers: Mapping[str, ToolHandler],
        needs: Needs = Needs(),
        *,
        rounds: int = 6,
        conclude: bool = False,
        judge: Callable[[str], Sequence[str] | Awaitable[Sequence[str]]] | None = None,
        corrections: int = 2,
        keep_chars: int | None = None,
    ) -> Completion:
        """Asks, calls the tools the model asks for, gives it what they
        returned, until it answers — `rounds` at most. A tool that fails
        says so to the model; one it made up is said unknown. `conclude`:
        the last round is not offered the tools — it answers with what it
        read — rather than end in ToolRoundsError; and a model that asks
        for one even then is asked once more with none declared at all,
        what it read given as text (`_concluded`). `judge`: what is wrong
        with its answer — said back to it with its answer, `corrections`
        times at most, its tools still offered to read what it lacks; then
        its answer as it is (2026-10-22: any model, the same deliverable) —
        `judge` may be a coroutine (2026-10-30: a draft's checks read the
        repository). `keep_chars`: the conversation kept within that many
        characters, the oldest tools' results dropped first, said so — a long
        task's state is in its draft, not in what it read (2026-10-30). The
        same call made again and again, answered the same, is said to the
        model (stuck)."""
        messages = list(request.messages)
        # An empty answer told, never retried as a failure.
        request = replace(request, empty_ok=True)
        asking = request
        left = corrections if judge is not None else 0
        calls: list[str] = []
        empty = MOST_EMPTY
        for round_ in range(rounds):
            last = conclude and round_ == rounds - 1
            if last:
                asking = replace(asking, tool_choice=ToolChoice.NONE)
            if keep_chars is not None:
                messages = condensed(messages, len(request.messages), keep_chars)
            done = await self.complete(replace(asking, messages=messages), needs)
            if not done.tool_calls and not done.text.strip():
                # Nothing said (2026-10-30): told so, asked again; past
                # MOST_EMPTY, its last word asked with no tool.
                if not empty or last:
                    return await self._concluded(replace(request, empty_ok=False), messages, needs)
                empty -= 1
                messages += [Message(Role.ASSISTANT, "…"), Message.user(EMPTY_SAID)]
                asking = replace(request, tool_choice=ToolChoice.AUTO)
                continue
            if not done.tool_calls:
                problems: list[str] = []
                if judge is not None and left and not last:
                    said = judge(done.text)
                    problems = list(await said if inspect.isawaitable(said) else said)
                if not problems:
                    return done
                left -= 1
                logger.info(
                    "model_answer_corrected", purpose=request.purpose, problems=problems[:3]
                )
                messages += [
                    Message(Role.ASSISTANT, done.text),
                    Message.user(
                        " ".join(problems)
                        + " Write the whole deliverable again, corrected — every section, "
                        "and only the deliverable."
                    ),
                ]
                asking = replace(request, tool_choice=ToolChoice.AUTO)
                continue
            if last:
                # It would not stop reading, tools refused: its calls are
                # not run; it is asked again with no tool to call.
                return await self._concluded(replace(request, empty_ok=False), messages, needs)
            messages.append(Message(Role.ASSISTANT, done.text, tool_calls=done.tool_calls))
            for tool_call in done.tool_calls:
                handler = handlers.get(tool_call.name)
                if handler is None:
                    result = json.dumps({"error": f"no tool named {tool_call.name}"})
                else:
                    try:
                        result = await handler(tool_call.arguments)
                    except Exception as error:
                        logger.warning("model_tool_failed", tool=tool_call.name, exc_info=True)
                        result = json.dumps({"error": type(error).__name__})
                result = stuck_said(calls, tool_call.name, tool_call.arguments, result)
                messages.append(
                    Message(Role.TOOL, result, tool_call_id=tool_call.id, name=tool_call.name)
                )
            # Its first move may be forced; after it, it may answer.
            asking = replace(request, tool_choice=ToolChoice.AUTO)
        raise ToolRoundsError(f"No answer after {rounds} rounds of tools.")

    async def _concluded(
        self, request: Request, messages: Sequence[Message], needs: Needs
    ) -> Completion:
        """The last word of a model that would not stop calling tools: the
        conversation as it began, what its tools returned given as text,
        no tool declared — every provider answers that."""
        read = _what_was_read(messages[len(request.messages) :])
        # Joined to the request's own last words, not after them: some
        # providers refuse two turns of the same side in a row.
        began = list(request.messages)
        last = began.pop() if began and began[-1].role is Role.USER else None
        said = f"{last.content}\n\n{read}" if last is not None else read
        final = replace(
            request,
            messages=[*began, Message.user(said)],
            tools=(),
            tool_choice=ToolChoice.AUTO,
        )
        done = await self.complete(final, replace(needs, tools=False))
        if done.tool_calls or not done.text.strip():
            raise ToolRoundsError("No answer, even with no tool left to call.")
        return done

    # ── keeping it ──────────────────────────────────────────────────────────

    def _record(
        self,
        request: Request,
        route: Route,
        attempt: int,
        *,
        status: str,
        done: Completion | None = None,
        error: str | None = None,
    ) -> None:
        at = datetime.now(UTC)
        usage = done.usage if done is not None else None
        reported = usage is not None and usage.reported
        rate = (
            self._rates.at(route.endpoint.provider, route.profile.model, at)
            if self._rates is not None and usage is not None and reported
            else None
        )
        self._session.add(
            ModelCall(
                workspace_id=self._workspace_id,
                id=uuid.uuid4(),
                purpose=request.purpose[:100],
                ref=request.ref[:100] if request.ref else None,
                run_id=request.run_id,
                tier=request.tier.value,
                provider=route.endpoint.provider,
                model=route.profile.model[:120],
                version=done.version[:120] if done is not None else None,
                route=route.why,
                attempt=attempt,
                owner=route.endpoint.owner,
                status=status,
                error=error[:1000] if error else None,
                tokens_in=usage.tokens_in if usage else 0,
                tokens_out=usage.tokens_out if usage else 0,
                tokens_thinking=usage.tokens_thinking if usage else 0,
                tokens_cached=usage.tokens_cached if usage else 0,
                tool_calls=len(done.tool_calls) if done is not None else 0,
                usage_reported=reported,
                # Unknown — no rate, or no usage said — rather than 0.
                cost_usd=rate.cost(usage) if rate is not None and usage is not None else None,
                rate_id=rate.id if rate is not None else None,
                latency_ms=done.latency_ms if done is not None else 0,
                request_id=done.request_id[:200] if done is not None and done.request_id else None,
                at=at,
                user_id=actor.user_id if (actor := current_actor()) is not None else None,
            )
        )

    async def _mark(self, *, failed: str | None) -> None:
        row = await self.setting()
        if row is None:
            return
        row.status = "failed" if failed else "ok"
        row.status_detail = failed[:500] if failed else None
        row.tested_at = datetime.now(UTC)

    async def test(self) -> Tested:
        """The workspace's own model, asked a few words: whether it
        answered, why not, how fast. LEKA's is never tried in its place."""
        row = await self.setting()
        own = own_of(row) if row is not None else None
        if own is None:
            return Tested(
                False, "No model of the workspace's own is set, or it is off.", None, None, None
            )
        routing = route_of(Needs(), own=replace(own, exclusive=True), keys={}, default=("", ""))
        if not routing.routes:
            return Tested(False, "This model cannot be used.", None, own.model, None)
        request = Request(
            purpose="model.test",
            tier=Tier.FAST,
            max_tokens=16,
            messages=[Message.user("Reply with the word OK.")],
        )
        attempts: list[Attempt] = []
        retries, self._retries = self._retries, 0
        try:
            done = await self._one(request, routing.routes[0], None, attempts)
        finally:
            self._retries = retries
        if done is None:
            detail = attempts[-1].error if attempts else "No answer."
            await self._mark(failed=detail)
            await self._session.flush()
            return Tested(False, detail, None, own.model, None)
        await self._mark(failed=None)
        await self._session.flush()
        return Tested(True, None, done.latency_ms, own.model, done.version)


# The tools' results a conversation keeps whole however long it grows: the
# latest ones, what the model works on now.
KEPT_WHOLE = 8
DROPPED = (
    "[LEKA dropped this result to keep the conversation short. Call the tool again if you "
    "need it; your draft and your plan are kept whole.]"
)
# The same call answered the same this many times in a row: said stuck.
STUCK_AFTER = 3
# An empty answer, told this many times at most.
MOST_EMPTY = 2
EMPTY_SAID = (
    "Your last answer was empty. Give your deliverable now, whole, as your instructions ask — "
    "or call the tool you still need."
)


def condensed(messages: list[Message], start: int, most: int) -> list[Message]:
    """The conversation within `most` characters: the oldest tools' results
    after the request's own messages (`start`) dropped first, each said
    dropped — never the request, never the latest KEPT_WHOLE results, never
    a call without its result (2026-10-30)."""
    size = sum(len(m.content or "") for m in messages)
    if size <= most:
        return messages
    results = [i for i, m in enumerate(messages) if i >= start and m.role is Role.TOOL]
    kept = list(messages)
    for at in results[:-KEPT_WHOLE] if len(results) > KEPT_WHOLE else []:
        if size <= most:
            break
        old = kept[at]
        if old.content == DROPPED:
            continue
        size -= len(old.content or "") - len(DROPPED)
        kept[at] = replace(old, content=DROPPED)
    return kept


def stuck_said(calls: list[str], name: str, arguments: Mapping[str, Any], result: str) -> str:
    """A tool's result — told, the same call answered the same STUCK_AFTER
    times in a row, that repeating it will not help (2026-10-30)."""
    key = json.dumps([name, arguments, result], sort_keys=True, default=str)
    calls.append(key)
    if len(calls) >= STUCK_AFTER and len(set(calls[-STUCK_AFTER:])) == 1:
        return (
            f"{result}\n\nNOTE: you made this same call {STUCK_AFTER} times and got the same "
            "answer: calling it again will not help. Change what you ask, or do something else."
        )
    return result


async def leka_complete(
    request: Request,
    needs: Needs = Needs(),
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    keys: dict[str, str | None] | None = None,
    default: tuple[str, str] | None = None,
    fallbacks: Sequence[tuple[str, str]] | None = None,
    retries: int | None = None,
    sleep: Sleep = asyncio.sleep,
) -> Completion:
    """LEKA's own models, for LEKA's own work — no workspace's, so no
    customer's credits, controls or own model: its interface translated
    into a language (2026-10-30). The default, then the fallbacks, each
    tried again while it says its failure is temporary. NoModelError when
    none answered."""
    own_keys = keys if keys is not None else leka_keys()
    routing = route_of(
        replace(needs, structured=needs.structured or request.output is not None),
        own=None,
        keys=own_keys,
        default=default or leka_default(),
        fallbacks=list(fallbacks)
        if fallbacks is not None
        else fallbacks_of(settings.llm_fallbacks),
        urls=leka_urls() if keys is None else {},
    )
    if not routing.routes:
        raise NoModelError("No language model is configured.", passed=routing.passed, reason="none")
    tries = max(0, settings.llm_retries if retries is None else retries)
    attempts: list[Attempt] = []
    for route in routing.routes[:MOST_MODELS]:
        vendor = provider(route.endpoint.provider)
        if vendor is None:
            continue
        circuit = f"model:{route.endpoint.provider}:leka"
        if not await breaker.allow(circuit):
            continue
        call = Call(
            route.endpoint,
            route.profile.model,
            replace(request, max_tokens=min(request.max_tokens, route.profile.output))
            if route.profile.output
            else request,
            thinking=route.profile.thinking,
            sends_temperature=route.profile.sends_temperature,
            forces_tools=route.profile.forces_tools,
            responses=route.profile.responses,
        )
        for attempt in range(1, tries + 2):
            try:
                async with httpx.AsyncClient(
                    transport=transport, timeout=wait_of(call.request)
                ) as client:
                    done = await vendor.complete(call, client)
                if not done.text.strip():
                    raise ProviderError("An empty answer.", retryable=True)
            except (ProviderError, httpx.HTTPError) as raised:
                error = _said(raised)
                attempts.append(
                    Attempt(
                        route.endpoint.provider,
                        route.profile.model,
                        "leka",
                        route.why,
                        attempt,
                        str(error),
                    )
                )
                logger.warning(
                    "leka_model_call_failed",
                    purpose=request.purpose,
                    provider=route.endpoint.provider,
                    model=route.profile.model,
                    status=error.status,
                    attempt=attempt,
                )
                if error.retryable and attempt <= tries:
                    await sleep(min(error.retry_after or 2.0 ** (attempt - 1), LONGEST_WAIT))
                    continue
                if _down(raised, error):
                    await breaker.failure(circuit)
                break
            await breaker.success(circuit)
            logger.info(
                "leka_model_call",
                purpose=request.purpose,
                provider=done.provider,
                model=done.model,
                tokens_in=done.usage.tokens_in,
                tokens_out=done.usage.tokens_out,
            )
            return done
    raise NoModelError("No language model answered.", attempts, routing.passed)


def _down(raised: Exception, error: ProviderError) -> bool:
    """Whether the provider itself failed — unreachable, slow, overloaded,
    erring — as a circuit breaker counts it. An answer that is empty, not the
    shape asked or refused for the request's own fault says nothing about
    whether the provider is up."""
    if isinstance(raised, BlockedAddressError):
        return False  # our refusal of the address, not the provider's failure
    if isinstance(raised, httpx.HTTPError):
        return True
    return error.status is not None and (error.status >= 500 or error.status == 429)


def _said(raised: Exception) -> ProviderError:
    """A transport failure as a provider error: a refused address is not
    temporary, a timeout or a dropped connection is."""
    if isinstance(raised, ProviderError):
        return raised
    if isinstance(raised, BlockedAddressError):
        return ProviderError(f"Refused address: {raised}", retryable=False)
    if isinstance(raised, httpx.TimeoutException):
        return ProviderError("No answer in time.", retryable=True)
    return ProviderError(f"Unreachable: {type(raised).__name__}", retryable=True)
