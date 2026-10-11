"""Running an agent (LEKA-395): asked, queued, run by a worker, kept.

    POST /agent-runs ──▶ AgentRuntime.start: the agent as the catalogue holds
                         it, usable here by this person, given what its
                         contract takes — refused, said why, nothing kept —
                         or kept queued; committed, then queued for a worker
    run_agent ─────────▶ execute_run:
        1. claimed: queued → running, by one worker only
        2. checked again, as things stand NOW: the agent still usable here,
           the person who asked still allowed — their role read now, never
           the one they had when they asked
        3. its context: the one it was given (an intention's), or assembled
           from what it was given — only what its entity types allow
           (runtime.inject)
        4. its tools: offered when read-only and permitted, each call kept
           with what came of it (tools.py)
        5. the model, through the gateway: run_tools, deep tier, what its
           definition needs choosing the model — within RUN_BUDGET, at most
           TOOL_ROUNDS rounds of tools, the last offered none: it answers
           with what it read
        6. what LEKA draws of it, when the agent says so (`renders`): the
           architect's PowerPoint and PDF (delivery.py)
        7. succeeded with what it delivered, or failed saying why — unless
           it was cancelled meanwhile: then that stands
    THE SWEEP (agent-runs-sweep): a run no worker will finish — running past
    ABANDONED, queued past FORGOTTEN — failed, `abandoned`.

Every step is an event (agent_run_events), append-only; every call to a
model is kept by the gateway with the run as its ref (`agent_run:<id>`).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import JobQueue, enqueue_job
from leka.capabilities.catalogue import CatalogueService, Entry, needs_of
from leka.capabilities.definition import Definition, check_input
from leka.capabilities.delivery import draw
from leka.capabilities.gateway import (
    Completion,
    Gateway,
    NoModelError,
    Request,
    Tier,
    Tool,
    ToolRoundsError,
)
from leka.capabilities.models import AgentRun, AgentRunEvent
from leka.capabilities.repository import CapabilityRunRepository, stale_runs
from leka.capabilities.runtime import (
    AgentTool,
    Injected,
    Refusal,
    RunStatus,
    inject,
    messages,
    offered,
    output_of,
    runnable,
)
from leka.capabilities.skills import SkillRuntime, agent_skill_tools, skill_handlers
from leka.capabilities.tools import TOOLS, Answer, handlers
from leka.connectors import SourceRepository
from leka.context import AssembledContext, ContextRepository, ContextService, IntentAsk
from leka.db import hidden_entities, session_factory, system_scope, workspace_scope
from leka.governance import (
    ROLE_PERMISSIONS,
    Permission,
    Resource,
    Target,
    audit,
    evaluate,
    hidden_on_behalf,
    record,
    subject_of,
)
from leka.ingestion import ContentRepository, ResolutionRepository
from leka.knowledge import EntityRepository, GraphRepository, GraphService, KnowledgeService
from leka.platform import Role

logger = structlog.get_logger(__name__)

RUN_JOB = "leka.capabilities.runs.run_agent"
# How long a run may take, all of it: its context, its tools, its model.
RUN_BUDGET = 15 * 60.0
# A run found running this long had its worker go away; one queued this
# long, its job.
ABANDONED = timedelta(minutes=30)
FORGOTTEN = timedelta(hours=6)
# What an agent may write, at most: a deck's worth of markdown.
MAX_TOKENS = 16_000
# Rounds of tools an agent may take before it answers. Its last round is
# offered none: it answers with what it read, rather than fail — the
# architect's instructions ask it to look brick by brick.
TOOL_ROUNDS = 16
# What is kept of what a tool was asked, and of what it delivered.
ARGUMENTS_KEPT = 500
OUTPUT_KEPT = 200_000


def now_or(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def capability_resource(definition: Definition) -> Resource:
    """A capability, as policies read it (LEKA-403): its risk, kind,
    category."""
    return Resource(
        "capability",
        definition.key,
        attributes={
            "risk": definition.risk,
            "kind": definition.kind.value,
            "category": definition.category,
        },
    )


def permissions_of(role: Role) -> frozenset[str]:
    return frozenset(p.value for p in ROLE_PERMISSIONS[role])


def reasons_of(entry: Entry) -> tuple[Mapping[str, object], ...]:
    return tuple({"code": r.code, **r.detail} for r in entry.availability.reasons)


def refusal_of(entry: Entry | None, inputs: Mapping[str, object]) -> Refusal | None:
    """Why it cannot run here, by this person, with this — none when it can."""
    if entry is None:
        return Refusal("not_found")
    if not runnable(entry.definition):
        return Refusal("not_an_agent")
    if not entry.availability.available:
        codes = entry.availability.codes
        return Refusal(
            "not_permitted" if codes == ("not_permitted",) else "unavailable", reasons_of(entry)
        )
    errors = check_input(entry.definition.contract, inputs)
    if errors:
        return Refusal("invalid_input", tuple({"name": e.name, "code": e.code} for e in errors))
    return None


class Steps:
    """A run's events, in order — each one written as it happens."""

    def __init__(self, session: AsyncSession, run: AgentRun, seq: int) -> None:
        self._session = session
        self._run = run
        self._seq = seq

    async def save(self) -> None:
        """What happened so far, seen by whoever looks: committed."""
        await self._session.commit()

    def add(self, kind: str, /, **detail: object) -> None:
        # Positional only: a failure's detail may say its own `kind` (the
        # error's type).
        self._seq += 1
        self._session.add(
            AgentRunEvent(
                workspace_id=self._run.workspace_id,
                id=uuid.uuid4(),
                run_id=self._run.id,
                seq=self._seq,
                kind=kind,
                at=now_or(),
                detail=detail,
            )
        )


async def queue_run(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    """Its job, for a worker: a person waits on it."""
    job = await enqueue_job(
        RUN_JOB,
        str(workspace_id),
        str(run_id),
        for_workspace_id=workspace_id,
        queue=JobQueue.HIGH,
        concurrency_key=f"agent-run:{run_id}",
    )
    return job is not None


# ── a run ──────────────────────────────────────────────────────────────────

ToolHandler = Callable[[Mapping[str, Any]], Awaitable[str]]


class _Offered(Mapping[str, ToolHandler]):
    """The tools offered, as the gateway calls them — each call kept with
    what came of it; one the model made up, answered unknown and kept like
    any other."""

    def __init__(
        self,
        bound: Mapping[str, Callable[[Mapping[str, Any]], Awaitable[Answer]]],
        steps: Steps,
        run: AgentRun,
    ) -> None:
        self._bound = bound
        self._steps = steps
        self._run = run

    def __getitem__(self, name: str) -> ToolHandler:
        async def call(arguments: Mapping[str, Any]) -> str:
            started = time.monotonic()
            tool = self._bound.get(name)
            try:
                said = (
                    await tool(arguments)
                    if tool is not None
                    else Answer(json.dumps({"error": f"no tool named {name}"}), "unknown")
                )
            except Exception as error:
                logger.warning("agent_tool_failed", tool=name, exc_info=True)
                said = Answer(json.dumps({"error": type(error).__name__}), "failed", "error")
            self._run.tool_calls += 1
            self._steps.add(
                "tool",
                name=name[:100],
                arguments=json.dumps(dict(arguments), ensure_ascii=False, default=str)[
                    :ARGUMENTS_KEPT
                ],
                outcome=said.outcome,
                why=said.why,
                ms=int((time.monotonic() - started) * 1000),
            )
            await self._steps.save()
            return said.text

        return call

    def __iter__(self) -> Iterator[str]:
        return iter(self._bound)

    def __len__(self) -> int:
        return len(self._bound)


def _contexts(session: AsyncSession, workspace_id: uuid.UUID) -> ContextService:
    return ContextService(
        ContextRepository(session, workspace_id),
        GraphService(GraphRepository(session, workspace_id)),
        content=ContentRepository(session, workspace_id),
        resolution=ResolutionRepository(session, workspace_id),
        sources=SourceRepository(session, workspace_id),
    )


async def _context(
    session: AsyncSession, run: AgentRun, definition: Definition
) -> AssembledContext | None:
    """The context it reads: the one it was given, as it stands — or one
    assembled from the words it was given, kept like any other."""
    contexts = _contexts(session, run.workspace_id)
    if run.context_id is not None:
        return await contexts.assembled(run.context_id)
    words = " ".join(str(v) for v in run.inputs.values() if isinstance(v, str)).strip()
    if len(words) < 3:
        return None
    return await contexts.assemble_intent(
        IntentAsk(text=words[:2000], title=definition.title[:300]), by=run.requested_by
    )


async def execute_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    tools: Sequence[AgentTool] = TOOLS,
    budget: float = RUN_BUDGET,
) -> dict[str, object]:
    """One run, end to end — idempotent: a run no longer queued is not run
    again."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            runs = CapabilityRunRepository(session, workspace_id)
            if not await runs.claim(run_id, at=now_or()):
                await session.rollback()
                return {"status": "not_queued"}
            run = await runs.run(run_id)
            if run is None:  # pragma: no cover — claimed a moment ago
                return {"status": "gone"}
            await session.refresh(run)
            steps = Steps(session, run, await runs.last_seq(run_id))
            steps.add("started")
            await session.commit()
            # What the person who asked may not see, it does not either
            # (LEKA-402).
            hidden = await hidden_on_behalf(session, workspace_id, run.requested_by)
            try:
                with hidden_entities(hidden):
                    return await _run(session, run, steps, tools, budget)
            except Exception as error:
                # Whatever happened, the run says it ended, and how.
                logger.exception("agent_run_failed", run=str(run_id), key=run.key)
                await session.rollback()
                await session.refresh(run)
                return await _fail(session, run, "error", kind=type(error).__name__)


def _ended(session: AsyncSession, run: AgentRun, status: str, **detail: object) -> None:
    """An agent run ended, as the audit trail keeps it (LEKA-407): LEKA ran
    it, for the person who asked."""
    audit(
        session,
        run.workspace_id,
        "ai",
        f"agent_run.{status}",
        outcome="success" if status == "succeeded" else "failure",
        target=Target("agent_run", run.id, run.key),
        detail={
            "agent": run.key,
            "version": run.version,
            "for": str(run.requested_by) if run.requested_by else None,
            **{k: v for k, v in detail.items() if v is not None},
        },
    )


async def _fail(
    session: AsyncSession, run: AgentRun, code: str, **detail: object
) -> dict[str, object]:
    runs = CapabilityRunRepository(session, run.workspace_id)
    ended = await runs.finish(
        run.id,
        status=RunStatus.FAILED.value,
        error=code,
        finished_at=now_or(),
        tool_calls=run.tool_calls,
        detail={**run.detail, **({"failure": detail} if detail else {})},
    )
    if ended:
        Steps(session, run, await runs.last_seq(run.id)).add("failed", code=code, **detail)
        _ended(session, run, "failed", error=code, reason=detail.get("reason"))
    await session.commit()
    logger.info("agent_run_ended", run=str(run.id), key=run.key, status="failed", error=code)
    return {"status": "failed" if ended else "cancelled", "error": code}


async def _run(
    session: AsyncSession,
    run: AgentRun,
    steps: Steps,
    tools: Sequence[AgentTool],
    budget: float,
) -> dict[str, object]:
    workspace_id = run.workspace_id
    # As things stand now: who asked, may they still; the agent, can it
    # still run here.
    # Their role now — a role of the workspace's own included — and the
    # policies in force (LEKA-403).
    subject = await subject_of(session, workspace_id, run.requested_by)
    if subject is None:
        return await _fail(session, run, "not_permitted")
    permissions = frozenset(p.value for p in subject.permissions)
    entry = await CatalogueService(session, workspace_id).entry(run.key, permissions=permissions)
    refused = refusal_of(entry, run.inputs)
    if refused is not None:
        return await _fail(
            session,
            run,
            "not_permitted" if refused.code == "not_permitted" else "unavailable",
            refused=refused.code,
            reasons=[dict(r) for r in refused.reasons],
        )
    assert entry is not None  # refusal_of said not_found otherwise
    definition = entry.definition
    decided = evaluate(
        subject,
        Permission(definition.permission),
        capability_resource(definition),
        action="agent:run",
    )
    if not decided.allowed:
        record(
            session,
            workspace_id,
            subject.user_id,
            subject.role,
            decided,
            action="agent:run",
            resource=capability_resource(definition),
            detail={"run": str(run.id), "when": "running"},
        )
        return await _fail(
            session, run, "not_permitted", refused=decided.reason, policy=decided.policy
        )
    if definition.version != run.version:
        run.detail = {**run.detail, "asked_version": run.version}
        run.version = definition.version

    # Its context, what its types allow.
    context = await _context(session, run, definition)
    injected = Injected(())
    if context is not None:
        run.context_id, run.context_version = context.context_id, context.version
        injected = inject(definition, [e.model_dump(mode="json") for e in context.elements])
    steps.add(
        "context",
        context=str(context.context_id) if context is not None else None,
        version=context.version if context is not None else None,
        given=len(injected.elements),
        out_of_scope=injected.out_of_scope,
        beyond=injected.beyond,
    )
    # Its tools: those it declares (LEKA-400), what it may use, by who asked.
    declared = [t for t in tools if not definition.tools or t.name in definition.tools]
    given, withheld = offered(declared, permissions)
    # Its skills: those it names, within what it reads (LEKA-401).
    named, out_of_reach = agent_skill_tools(definition)
    skilled, unskilled = offered(named, permissions)
    given, withheld = [*given, *skilled], [*withheld, *out_of_reach, *unskilled]
    for kept in withheld:
        steps.add("tool_withheld", name=kept.tool, why=kept.why)
    await session.commit()

    bound = handlers(
        definition,
        GraphService(GraphRepository(session, workspace_id)),
        KnowledgeService(EntityRepository(session, workspace_id)),
    )
    # Each skill call checked and kept (skill_runs), about this run.
    bound |= skill_handlers(
        SkillRuntime(
            session,
            workspace_id,
            permissions=permissions,
            by=run.requested_by,
            caller=f"agent:{definition.key}",
            ref=f"agent_run:{run.id}",
        ),
        [t.name for t in skilled],
    )
    request = Request(
        purpose=f"agent:{definition.key}"[:100],
        messages=messages(definition, run.inputs, injected, tools=given),
        tier=Tier.DEEP,
        max_tokens=MAX_TOKENS,
        tools=[Tool(t.name, t.description, t.parameters) for t in given],
        ref=f"agent_run:{run.id}",
    )
    offered_now = _Offered({t.name: bound[t.name] for t in given if t.name in bound}, steps, run)
    try:
        done: Completion = await asyncio.wait_for(
            Gateway(session, workspace_id).run_tools(
                request,
                offered_now,
                replace(needs_of(definition), tools=bool(given)),
                rounds=TOOL_ROUNDS,
                conclude=True,
            ),
            timeout=budget,
        )
    except ToolRoundsError:
        return await _fail(session, run, "tool_rounds")
    except NoModelError as error:
        # Why, an AI control's own included: refused, limited, blocked
        # (LEKA-406).
        return await _fail(
            session,
            run,
            "no_model",
            said=str(error),
            tried=len(error.attempts),
            reason=error.reason,
        )
    except TimeoutError:
        return await _fail(session, run, "timeout", seconds=budget)

    steps.add(
        "answered",
        provider=done.provider,
        model=done.model,
        version=done.version,
        tokens_in=done.usage.tokens_in,
        tokens_out=done.usage.tokens_out,
    )
    output = output_of(done.text, run.format)
    if output is None:
        return await _fail(session, run, "invalid_output", format=run.format)
    # What LEKA draws of it — the architect's deck (delivery.py): its files,
    # or why there are none; the analysis stands either way.
    detail = dict(run.detail)
    if definition.renders is not None:
        await session.commit()
        drawn = await draw(session, run, definition, output)
        if drawn.error is None:
            steps.add(
                "rendered",
                formats=[f["format"] for f in drawn.files],
                slides=drawn.files[0]["slides"] if drawn.files else 0,
                **(drawn.usage or {}),
            )
        else:
            steps.add("render_failed", code=drawn.error)
        detail |= drawn.detail()
    runs = CapabilityRunRepository(session, workspace_id)
    ended = await runs.finish(
        run.id,
        status=RunStatus.SUCCEEDED.value,
        output=output[:OUTPUT_KEPT],
        finished_at=now_or(),
        provider=done.provider,
        model=done.model[:120],
        model_version=done.version[:120],
        tool_calls=run.tool_calls,
        detail=detail,
    )
    if ended:
        steps.add("succeeded", chars=len(output))
        _ended(session, run, "succeeded", model=done.model, tool_calls=run.tool_calls)
    await session.commit()
    status = "succeeded" if ended else "cancelled"
    logger.info("agent_run_ended", run=str(run.id), key=run.key, status=status)
    return {"status": status}


def run_agent(workspace_id: str, run_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(execute_run(uuid.UUID(workspace_id), uuid.UUID(run_id)))


# ── the sweep ──────────────────────────────────────────────────────────────


async def sweep_runs(*, now: datetime | None = None, limit: int = 200) -> dict[str, int]:
    """Every run no worker will finish, failed — `abandoned`. Idempotent."""
    moment = now_or(now)
    with system_scope():
        async with session_factory() as session:
            stale = await stale_runs(
                session,
                running_before=moment - ABANDONED,
                queued_before=moment - FORGOTTEN,
                limit=limit,
            )
    swept = 0
    for workspace_id, run_id in stale:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                runs = CapabilityRunRepository(session, workspace_id)
                run = await runs.run(run_id, lock=True)
                if run is None or run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
                    continue
                was = run.status
                run.status = RunStatus.FAILED.value
                run.error = "abandoned"
                run.finished_at = moment
                steps = Steps(session, run, await runs.last_seq(run_id))
                steps.add("failed", code="abandoned", was=was)
                await session.commit()
                swept += 1
    logger.info("agent_runs_swept", abandoned=swept)
    return {"abandoned": swept}


def run_runs_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(sweep_runs())
