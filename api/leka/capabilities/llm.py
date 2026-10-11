"""The LLM runtime (LEKA-429): how a LEKA feature has a language model do a
piece of work — the one way, for Intentions, Mon environnement, Capacités,
the agents, the skills and the workflows. Above the gateway (gateway/),
which knows the vendors; below every feature, which knows none.

    a Task       what it is for; its instructions; what is asked; the LEKA
                 context that grounds it — a ContextPack: the Context
                 Engine's elements, the company model's facts, each with an
                 id to cite; the shape of the answer and how to check it;
                 what it needs of a model; how long it may take; the tools
                 it may read through
        ──▶ run()   through the gateway — the model chosen by what the task
                    needs, retries, fallback (LEKA-394)
        ──▶ checked: its shape (a pydantic model), then the task's own check
                    (what it cites is in its context…) — an answer failing
                    either is not handed on
        ──▶ an Execution: succeeded, invalid, no_model, timed_out, failed —
                    a model's failure is a status, never an exception the
                    feature must guess at — who answered (provider, model,
                    version), its tokens and latency, how many calls it took;
                    kept (llm_runs), its calls with it (model_calls.run_id)

What the runtime never does: act. A tool a model may call READS; one that
would change something cannot be given to it (SensitiveToolError). What a
model says should be done is, at most, a proposal — and only LEKA's
intention flow carries one out: a person's decision under the workspace's
policy (LEKA-390), through the systems it authorized (LEKA-391).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.gateway import (
    Completion,
    Gateway,
    Message,
    Needs,
    NoModelError,
    Output,
    Request,
    Tier,
    Tool,
    ToolChoice,
)
from leka.capabilities.gateway.service import InvalidOutputError, ToolRoundsError, json_of
from leka.capabilities.models import LLMRun, ModelAsk, ModelCall
from leka.core import languages

logger = structlog.get_logger(__name__)

# Said to every model, whatever the task: what LEKA asks of any of them.
GUARDRAILS = """Rules that hold for every task LEKA gives you:
- Use only what you are given: the task, and the LEKA context with its ids. \
Never invent a name, a figure, a date, an owner or a cause.
- When you rest on something from the context, cite its id, exactly.
- You never act on anyone's systems. When something should be done, say so \
as a proposal; a person decides, and LEKA alone carries it out."""

# How much context a task sends, at most (characters: about 4 a token).
CONTEXT_CHARACTERS = 24_000


class SensitiveToolError(ValueError):
    """A tool that would change something, offered to a model: refused."""


@dataclass(frozen=True)
class ContextItem:
    """One thing LEKA knows, as a model reads it — with the id to cite."""

    id: str
    kind: str
    text: str
    sources: tuple[str, ...] = ()

    def said(self) -> dict[str, Any]:
        found: dict[str, Any] = {"id": self.id, "kind": self.kind, "text": self.text}
        if self.sources:
            found["sources"] = list(self.sources)
        return found


@dataclass(frozen=True)
class ContextPack:
    """The LEKA context a task gives its model: what grounds the answer, and
    what an answer may cite. `ref`: where it was read (a context, its
    version)."""

    items: tuple[ContextItem, ...] = ()
    ref: str | None = None
    # How many were left out for its size.
    left_out: int = 0

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(item.id for item in self.items)

    def said(self) -> list[dict[str, Any]]:
        return [item.said() for item in self.items]

    def plus(self, *items: ContextItem) -> ContextPack:
        known = self.ids
        return ContextPack(
            (*self.items, *(i for i in items if i.id not in known)), self.ref, self.left_out
        )

    @classmethod
    def of(
        cls,
        items: Sequence[ContextItem],
        *,
        ref: str | None = None,
        characters: int = CONTEXT_CHARACTERS,
    ) -> ContextPack:
        """As many as fit, in the order given — the most relevant first."""
        kept: list[ContextItem] = []
        used = 0
        for item in items:
            size = len(item.text) + len(item.id) + 40
            if used + size > characters:
                break
            kept.append(item)
            used += size
        return cls(tuple(kept), ref, len(items) - len(kept))

    @classmethod
    def of_context(cls, context: Any, *, characters: int = CONTEXT_CHARACTERS) -> ContextPack:
        """A context the Context Engine assembled (LEKA-370): its elements as
        it ranked them, each in its one line for a model, where it came from."""
        items = [
            ContextItem(
                id=f"{element.kind}:{element.ref_id}",
                kind=element.ref_type,
                text=element.text or element.label,
                sources=tuple(
                    sorted({s.kind or s.name or "" for s in element.provenance.sources} - {""})
                ),
            )
            for element in sorted(context.elements, key=lambda e: e.position)
        ]
        return cls.of(
            items, ref=f"context:{context.context_id}:v{context.version}", characters=characters
        )


Handler = Callable[[Mapping[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class RuntimeTool:
    """A function a model may ask LEKA to call — to READ. `effect` says
    what it does; anything but `read` is refused: a model never acts."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: Handler
    effect: str = "read"

    def __post_init__(self) -> None:
        if self.effect != "read":
            msg = (
                f"{self.name}: a tool that would {self.effect} cannot be given to a model — "
                "an action goes through a person's decision (LEKA-390)"
            )
            raise SensitiveToolError(msg)


Check = Callable[[Any, ContextPack], Sequence[str]]


@dataclass(frozen=True)
class Task:
    """A piece of work for a language model."""

    # intention.understanding, capability.synthesis, enrichment.summary,
    # agent:<key>…: what usage, audit and the router read.
    purpose: str
    instructions: str
    # What is asked: words, or an object said as JSON.
    input: str | Mapping[str, Any]
    context: ContextPack = field(default_factory=ContextPack)
    # The answer's shape; none: text.
    output: type[BaseModel] | None = None
    # Its own check, once the shape holds: what is wrong — nothing, it is used.
    check: Check | None = None
    needs: Needs = field(default_factory=Needs)
    tier: Tier = Tier.STANDARD
    max_tokens: int = 2000
    # Seconds for all of it, then timed_out.
    budget: float = 60.0
    tools: Sequence[RuntimeTool] = ()
    # Rounds of tools at most; `conclude`: the last one must answer — the
    # model is not offered its tools again — rather than end in failure.
    rounds: int = 6
    conclude: bool = False
    # What it is about — an intention, a capability's run.
    ref: str | None = None
    # The conversation, when the caller writes it (an agent's own rules and
    # instructions, ADR 004): then said as given — instructions, input and
    # context being already in it — the rest of the runtime unchanged.
    messages: Sequence[Message] | None = None
    # The language to write in (a tag of leka/core/languages.yaml): the
    # person's, or the workspace's for what it shares. None: the model
    # follows the instructions alone.
    language: str | None = None


@dataclass(frozen=True)
class Execution:
    """What came of a task: what to use, and what it took."""

    # succeeded, invalid, no_model, timed_out, failed
    status: str
    value: Any = None
    text: str | None = None
    provider: str | None = None
    model: str | None = None
    version: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    calls: int = 0
    error: str | None = None
    run_id: uuid.UUID | None = None

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"


def cites(value: Any, field_name: str = "cites") -> set[str]:
    """Every id a structured answer cites, under `field_name`, however deep."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, BaseModel):
            walk(node.model_dump())
        elif isinstance(node, Mapping):
            for key, item in node.items():
                if key == field_name and isinstance(item, list):
                    found.update(str(i) for i in item)
                else:
                    walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return found


class LLMRuntime:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        *,
        gateway: Gateway | None = None,
    ) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._gateway = gateway or Gateway(session, workspace_id)

    async def ready(self, needs: Needs = Needs()) -> bool:
        """Whether a model this workspace can reach does what is needed."""
        return await self._gateway.ready(needs)

    # What a model was already asked (model_asks) ─────────────────────────────

    async def asked(self, purpose: str, keys: Sequence[str]) -> dict[str, str]:
        """For each key a model was already asked about for this purpose,
        the digest of the facts it was asked on."""
        if not keys:
            return {}
        rows = await self._session.execute(
            select(ModelAsk.key, ModelAsk.digest).where(
                ModelAsk.workspace_id == self._workspace_id,
                ModelAsk.purpose == purpose[:100],
                ModelAsk.key.in_([k[:300] for k in keys]),
            )
        )
        return dict(rows.tuples().all())

    async def remember(
        self,
        purpose: str,
        digests: Mapping[str, str],
        *,
        answered: Collection[str] = (),
        at: datetime | None = None,
    ) -> None:
        """That a model was asked about these keys on these facts — and
        which it said something of. Asked again only once the facts change."""
        if not digests:
            return
        moment = at or datetime.now(UTC)
        held = {
            row.key: row
            for row in (
                await self._session.execute(
                    select(ModelAsk).where(
                        ModelAsk.workspace_id == self._workspace_id,
                        ModelAsk.purpose == purpose[:100],
                        ModelAsk.key.in_([k[:300] for k in digests]),
                    )
                )
            ).scalars()
        }
        for key, digest in digests.items():
            row = held.get(key[:300])
            if row is None:
                row = ModelAsk(
                    workspace_id=self._workspace_id,
                    id=uuid.uuid4(),
                    purpose=purpose[:100],
                    key=key[:300],
                    digest=digest[:64],
                    asked_at=moment,
                )
                self._session.add(row)
            row.digest = digest[:64]
            row.answered = key in answered
            row.asked_at = moment
        await self._session.flush()

    def _messages(self, task: Task) -> list[Message]:
        if task.messages is not None:
            return list(task.messages)
        said: dict[str, Any] = {
            "task": task.input if isinstance(task.input, str) else dict(task.input)
        }
        if task.context.items:
            said["context"] = task.context.said()
        system = f"{task.instructions.strip()}\n\n{GUARDRAILS}"
        if task.language is not None:
            system = f"{system}\n- {languages.writing_rule(task.language)}"
        return [
            Message.system(system),
            Message.user(json.dumps(said, ensure_ascii=False, default=str)),
        ]

    async def run(self, task: Task) -> Execution:
        """The task, done — or why not, as a status. Never raises for a
        model's failure; kept, with its calls."""
        run_id = uuid.uuid4()
        started_at = datetime.now(UTC)
        started = time.monotonic()
        request = Request(
            purpose=task.purpose[:100],
            messages=self._messages(task),
            tier=task.tier,
            max_tokens=task.max_tokens,
            tools=[Tool(t.name, t.description, t.parameters) for t in task.tools],
            tool_choice=ToolChoice.AUTO,
            ref=task.ref,
            run_id=run_id,
        )
        status, value, done, error = "failed", None, None, None
        try:
            if task.output is not None and not task.tools:
                # Checked by the gateway: a shape or a check that fails is
                # asked again, then of the next model.
                read = await self._gateway.structured(
                    request,
                    task.output,
                    task.needs,
                    budget=task.budget,
                    verify=self._verify(task),
                )
                value, done = read.value, read.completion
            elif task.tools:
                # Its answer, once it stops calling tools, in the shape asked:
                # Gemini 3 and the OpenAI-shaped APIs take a schema beside
                # their tools.
                asking = (
                    replace(request, output=Output.of(task.output))
                    if task.output is not None
                    else request
                )
                done = await asyncio.wait_for(
                    self._gateway.run_tools(
                        asking,
                        {t.name: t.handler for t in task.tools},
                        task.needs,
                        rounds=task.rounds,
                        conclude=task.conclude,
                    ),
                    timeout=task.budget,
                )
                value = self._shaped(task, done) if task.output is not None else None
            else:
                done = await self._gateway.complete(request, task.needs, budget=task.budget)
            checked = value if value is not None else done.text
            problems = list(task.check(checked, task.context)) if task.check else []
            if problems:
                status, error, value = "invalid", "; ".join(problems)[:1000], None
            else:
                status = "succeeded"
        except ToolRoundsError:
            status, error = "failed", "tool_rounds"
        except NoModelError as raised:
            status = {
                "none": "no_model",
                "timeout": "timed_out",
            }.get(raised.reason, "failed")
            # Every model answered, never as asked: invalid.
            if (
                status == "failed"
                and raised.attempts
                and all(a.error.startswith("Not ") for a in raised.attempts)
            ):
                status = "invalid"
            # Why, said: the last model tried and what it answered.
            last = raised.attempts[-1] if raised.attempts else None
            error = f"{raised} {last.provider}/{last.model}: {last.error}" if last else str(raised)
        except InvalidOutputError as raised:
            status, error = "invalid", str(raised)
        except TimeoutError:
            status, error = "timed_out", f"No answer in {task.budget:g} s."
        except Exception as raised:
            logger.exception("llm_task_failed", purpose=task.purpose)
            status, error = "failed", type(raised).__name__
        latency = int((time.monotonic() - started) * 1000)
        execution = await self._keep(task, run_id, status, done, error, started_at, latency)
        return Execution(
            status=status,
            value=value if status == "succeeded" else None,
            text=done.text if done is not None and status == "succeeded" else None,
            provider=execution.provider,
            model=execution.model,
            version=execution.version,
            tokens_in=execution.tokens_in,
            tokens_out=execution.tokens_out,
            latency_ms=latency,
            calls=execution.calls,
            error=error,
            run_id=run_id,
        )

    @staticmethod
    def _verify(task: Task) -> Callable[[Any], Sequence[str]] | None:
        if task.check is None:
            return None
        check, context = task.check, task.context
        return lambda value: check(value, context)

    @staticmethod
    def _shaped(task: Task, done: Completion) -> Any:
        """The answer after tools, in its shape — InvalidOutputError if not."""
        if task.output is None:
            return None
        try:
            return task.output.model_validate_json(json_of(done.text))
        except ValidationError as error:
            raise InvalidOutputError("Not the shape asked.") from error

    async def _keep(
        self,
        task: Task,
        run_id: uuid.UUID,
        status: str,
        done: Completion | None,
        error: str | None,
        started_at: datetime,
        latency: int,
    ) -> LLMRun:
        await self._session.flush()
        totals = (
            await self._session.execute(
                select(
                    func.count(ModelCall.id),
                    func.coalesce(func.sum(ModelCall.tokens_in), 0),
                    func.coalesce(func.sum(ModelCall.tokens_out), 0),
                    func.sum(ModelCall.cost_usd),
                ).where(ModelCall.run_id == run_id)
            )
        ).one()
        row = LLMRun(
            workspace_id=self._workspace_id,
            id=run_id,
            purpose=task.purpose[:100],
            ref=task.ref[:100] if task.ref else None,
            status=status,
            provider=done.provider if done is not None else None,
            model=done.model if done is not None else None,
            version=done.version[:120] if done is not None else None,
            calls=int(totals[0] or 0),
            tokens_in=int(totals[1] or 0),
            tokens_out=int(totals[2] or 0),
            cost_usd=float(totals[3]) if totals[3] is not None else None,
            latency_ms=latency,
            context_ref=task.context.ref[:200] if task.context.ref else None,
            context_items=len(task.context.items),
            error=error[:1000] if error else None,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )
        self._session.add(row)
        await self._session.flush()
        logger.info(
            "llm_task_done",
            purpose=task.purpose,
            status=status,
            provider=row.provider,
            model=row.model,
            calls=row.calls,
            latency_ms=latency,
        )
        return row
