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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import JobQueue, enqueue_job
from leka.capabilities.catalogue import CatalogueService, Entry, needs_of
from leka.capabilities.code_tools import CODE_NAMES, CODE_TOOLS, code_handlers
from leka.capabilities.definition import Definition, check_input
from leka.capabilities.deliverable_check import deferred, missing, unread
from leka.capabilities.delivery import draw, organisation_of
from leka.capabilities.gateway import (
    Completion,
    Gateway,
    NoModelError,
    Request,
    Tier,
    Tool,
    ToolRoundsError,
)
from leka.capabilities.gateway.service import CUT
from leka.capabilities.method_tools import METHOD_NAMES, METHOD_TOOLS, method_handlers
from leka.capabilities.mockups import design_target
from leka.capabilities.models import AgentRun, AgentRunEvent
from leka.capabilities.repository import CapabilityRunRepository, stale_runs
from leka.capabilities.review import review_of
from leka.capabilities.runtime import (
    AgentTool,
    Injected,
    Refusal,
    RunStatus,
    Withheld,
    framed,
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
from leka.core.config import settings
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
from leka.identity import spoken_language
from leka.ingestion import ContentRepository, ResolutionRepository
from leka.knowledge import EntityRepository, GraphRepository, GraphService, KnowledgeService
from leka.platform import Role

logger = structlog.get_logger(__name__)

RUN_JOB = "leka.capabilities.runs.run_agent"
# A finished run's files drawn after it (2026-10-16): its deck, from the
# analysis it delivered — the run itself never done again.
FILES_JOB = "leka.capabilities.runs.draw_files"
# A code change written again from a finished run's analysis (2026-10-18),
# a design drawn again from its review.
CHANGE_JOB = "leka.capabilities.runs.rewrite_change_job"
DESIGN_JOB = "leka.capabilities.runs.redraw_design_job"
# One mock-up corrected as a person asked (2026-10-19).
CORRECT_JOB = "leka.capabilities.runs.correct_design_job"
# What LEKA draws of a run, written again on asking: the job, and the word
# its « being drawn » says.
REDRAWN = {"code_change": (CHANGE_JOB, "change"), "design_mockups": (DESIGN_JOB, "design")}
# The files a run read, named to be read again when its change is: at most.
MOST_READ_KEPT = 60
# The files a deck may be drawn as.
DECK_FILES = ("pdf", "pptx")
# Asked longer ago and still not drawn: lost (a worker gone) — asked again.
DRAWING_LOST = timedelta(minutes=20)
# How long a run may take, all of it: its context, its tools, its model.
RUN_BUDGET = 15 * 60.0
# A run found running this long had its worker go away; one queued this
# long, its job — said failed, never left « en cours » (2026-10-14).
ABANDONED = timedelta(minutes=30)
FORGOTTEN = timedelta(minutes=45)
# What an agent may write, at most: a deck's worth of markdown — its thinking
# counts: a security review was cut mid-sentence at 16,000 (2026-10-20). Each
# model is held to what it gives back at most (the gateway).
MAX_TOKENS = 48_000
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


# What read_content gives of one thing, at most: its latest records, the
# start of each.
MOST_RECORDS = 4
RECORD_CHARS = 6_000


def _contents(
    session: AsyncSession, workspace_id: uuid.UUID
) -> Callable[[uuid.UUID], Awaitable[list[dict[str, object]]]]:
    """What one thing's records say — the records it was read from, the
    latest first, the start of each: what read_content answers."""
    repository = ContentRepository(session, workspace_id)

    async def read(entity_id: uuid.UUID) -> list[dict[str, object]]:
        rows = await repository.evidence_of(entity_id, limit=MOST_RECORDS, chars=RECORD_CHARS)
        return [
            {
                "title": row.title,
                "kind": row.kind,
                "url": row.url,
                "updated_at": row.updated_at,
                "text": row.excerpt,
                "gone": row.deleted_at is not None,
            }
            for row in rows
        ]

    return read


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


# What an agent that declares no tools reads of the code, when a repository
# is connected (2026-10-23: the architect drew bricks no source names, the
# code it could not read).
READ_CODE = ("list_files", "read_file")


def code_tools_of(definition: Definition) -> tuple[str, ...]:
    """The code tools an agent is offered, a GitHub source connected: those
    it names — or, naming none, the reading of the code."""
    named = tuple(t.name for t in CODE_TOOLS if t.name in definition.tools)
    return named if definition.tools else READ_CODE


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
            # (LEKA-402) — nor, kept to some sources, what came from none of
            # them (2026-10-14).
            hidden = await hidden_on_behalf(session, workspace_id, run.requested_by)
            kept = run.detail.get("sources")
            if isinstance(kept, list) and kept:
                hidden = hidden | await outside_sources(
                    session, workspace_id, [str(s) for s in kept]
                )
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


async def _reads_code(session: AsyncSession, workspace_id: uuid.UUID) -> bool:
    """Whether a GitHub source is connected, its code there to read."""
    # Here, not at the top: changes.py reads the catalogue, which reads the
    # registry, which reads the code tools' names.
    from leka.capabilities.changes import github_sources

    return bool(await github_sources(session, workspace_id))


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
    # The code tools: only to an agent that names them (code_tools.py), and
    # only when there is code to read — a GitHub source connected; else the
    # model never hears of them (2026-10-18: the documentation assistant
    # reads the code when it can, and works without it).
    coded = [t for t in CODE_TOOLS if t.name in code_tools_of(definition)]
    no_code: list[Withheld] = []
    if coded and not await _reads_code(session, workspace_id):
        no_code, coded = [Withheld(t.name, "no_source") for t in coded], []
    declared += coded
    # Its method's guides: only to an agent that names them and has a library.
    declared += [t for t in METHOD_TOOLS if t.name in definition.tools and definition.method]
    given, withheld = offered(declared, permissions)
    withheld += no_code
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
        content=_contents(session, workspace_id),
    )
    # What it reads of pull requests and files, kept with the run: its
    # deliverable shows its comments on the diff it read (review.py); the
    # designer's mock-ups are drawn from the files (mockups.py).
    read: dict[str, Any] = {}
    reads_code = "read_file" in {t.name for t in given}
    if CODE_NAMES & {t.name for t in given}:
        bound |= code_handlers(session, workspace_id, read)
    if METHOD_NAMES & {t.name for t in given}:
        bound |= method_handlers(definition, settings.agents_dir)
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
    language = await spoken_language(session, run.requested_by, workspace_id)
    # Asked to implement a design review's direction: its mock-up, given —
    # never its words alone (2026-10-24).
    target = await design_target(session, run) if definition.renders == "code_change" else None
    if target is not None:
        steps.add("design_target", screen=target["screen"], direction=target["direction"])
    request = Request(
        purpose=f"agent:{definition.key}"[:100],
        messages=messages(
            definition,
            {**run.inputs, "maquette": target} if target is not None else run.inputs,
            injected,
            tools=given,
            language=language,
            organisation=await organisation_of(session, workspace_id),
        ),
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
                rounds=definition.rounds or TOOL_ROUNDS,
                conclude=True,
                # Its deliverable, every section its agent gives — whatever
                # the model; told what it lacks, it writes it again
                # (2026-10-22).
                # And every line it cites, read (2026-10-23).
                judge=lambda text: [
                    *missing(
                        definition.instructions or "",
                        text,
                        language=language or "fr",
                        framed=framed(definition),
                    ),
                    *(unread(text, read.get("files", {})) if reads_code else []),
                    # A design implemented whole, never by halves.
                    *(deferred(text) if target is not None else []),
                ],
                corrections=settings.agent_corrections,
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
    # Cut at its limit, it is said so — never delivered as done (2026-10-20).
    if str(done.finish or "").upper() in CUT:
        return await _fail(session, run, "invalid_output", format=run.format, cut=True)
    output = output_of(done.text, run.format)
    if output is None:
        return await _fail(session, run, "invalid_output", format=run.format)
    # Told and still short of a section: delivered, said incomplete — never
    # shown as whole.
    lacking = (
        missing(
            definition.instructions or "",
            done.text,
            language=language or "fr",
            framed=framed(definition),
        )
        if settings.agent_corrections
        else []
    )
    if lacking:
        steps.add("incomplete", said=lacking[0][:500])
    # What LEKA draws of it — the architect's deck (delivery.py): its files,
    # or why there are none; the analysis stands either way.
    detail = dict(run.detail)
    if read.get("pulls"):
        pulls = dict(read["pulls"])
        detail["pulls"] = list(pulls.values())
        detail["listed"] = read.get("listed") or {}
        review = review_of(output, pulls)
        if review is not None:
            detail["review"] = review
            steps.add(
                "reviewed",
                comments=len(review["comments"]),
                dropped=review["dropped"],
            )
    # Only the files a person asked for (2026-10-14: a PDF nobody asked for
    # was drawn) — every one when the run says nothing of it.
    asked = run.detail.get("formats")
    wanted = None if not isinstance(asked, list) else [str(f) for f in asked]
    # The files a code change or a design is drawn from, named: read again
    # when it is drawn again (rewrite).
    if definition.renders in REDRAWN and read.get("files"):
        detail["read_files"] = list(read["files"])[:MOST_READ_KEPT]
    if definition.renders is not None and (
        definition.renders != "architecture_deck" or wanted != []
    ):
        await session.commit()
        drawn = await draw(
            session, run, definition, output, formats=wanted, read=read.get("files") or {}
        )
        if drawn.error is None:
            steps.add(drawn.step, **drawn.said())
        else:
            steps.add("render_failed", code=drawn.error, said=drawn.refusal)
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


async def outside_sources(
    session: AsyncSession, workspace_id: uuid.UUID, sources: Sequence[str]
) -> frozenset[uuid.UUID]:
    """The things of the company model no source among these showed."""
    rows = await session.execute(
        text(
            """
            SELECT e.id FROM entities e
             WHERE e.workspace_id = :workspace
               AND NOT EXISTS (
                   SELECT 1 FROM jsonb_array_elements(
                       COALESCE(e.provenance -> 'sources', '[]'::jsonb)
                   ) AS s
                    WHERE s ->> 'source_id' = ANY(:sources)
               )
            """
        ),
        {"workspace": workspace_id, "sources": list(sources)},
    )
    return frozenset(rows.scalars().all())


def run_agent(workspace_id: str, run_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(execute_run(uuid.UUID(workspace_id), uuid.UUID(run_id)))


# ── its files, after it ─────────────────────────────────────────────────────


async def queue_files(workspace_id: uuid.UUID, run_id: uuid.UUID, formats: Sequence[str]) -> bool:
    """Its files to draw, for a worker: a deck takes minutes."""
    job = await enqueue_job(
        FILES_JOB,
        str(workspace_id),
        str(run_id),
        ",".join(formats),
        for_workspace_id=workspace_id,
        queue=JobQueue.HIGH,
        concurrency_key=f"agent-run-files:{run_id}",
    )
    return job is not None


async def redraw(
    workspace_id: uuid.UUID, run_id: uuid.UUID, formats: Sequence[str]
) -> dict[str, object]:
    """A finished run's deck drawn as `formats`, from the analysis it
    delivered, and kept beside the files it has — said as a step of it.

    As a run draws (execute_run): what it needs read and committed first —
    no transaction, no lock held while the model writes the deck, minutes
    long — then the files kept. Whatever goes wrong, « being drawn » ends,
    said why: never left waiting (2026-10-16: it stayed « en préparation »)."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            try:
                return await _redraw(session, workspace_id, run_id, formats)
            except Exception:
                logger.exception("run_files_not_drawn", run=str(run_id))
                await session.rollback()
                runs = CapabilityRunRepository(session, workspace_id)
                run = await runs.run(run_id, lock=True)
                if run is not None:
                    Steps(session, run, await runs.last_seq(run_id)).add(
                        "render_failed", code="error"
                    )
                    run.detail = {
                        **run.detail,
                        "drawing": None,
                        "drawing_since": None,
                        "deliverables_error": "error",
                    }
                    await session.commit()
                return {"drawn": [], "error": "error"}


async def _redraw(
    session: AsyncSession, workspace_id: uuid.UUID, run_id: uuid.UUID, formats: Sequence[str]
) -> dict[str, object]:
    runs = CapabilityRunRepository(session, workspace_id)
    run = await runs.run(run_id)
    if run is None or run.status != RunStatus.SUCCEEDED or not run.output:
        return {"drawn": [], "skipped": "not_finished"}
    subject = await subject_of(session, workspace_id, run.requested_by)
    permissions = frozenset(p.value for p in subject.permissions) if subject else frozenset()
    entry = await CatalogueService(session, workspace_id).entry(run.key, permissions=permissions)
    if entry is None or entry.definition.renders != "architecture_deck":
        run.detail = {**run.detail, "drawing": None, "drawing_since": None}
        await session.commit()
        return {"drawn": [], "skipped": "not_drawn"}
    output = run.output
    # Nothing held while the model writes: minutes.
    await session.commit()
    drawn = await draw(session, run, entry.definition, output, formats=formats)
    # Then kept, the run read again as it is now.
    run = await runs.run(run_id, lock=True)
    if run is None:
        return {"drawn": [], "skipped": "gone"}
    steps = Steps(session, run, await runs.last_seq(run_id))
    had = run.detail.get("deliverables")
    kept = [
        f
        for f in (had if isinstance(had, list) else [])
        if isinstance(f, dict) and f.get("format") not in formats
    ]
    done = {"drawing": None, "drawing_since": None}
    if drawn.error is None:
        steps.add(drawn.step, **drawn.said())
        files = kept + list(drawn.files)
        run.detail = {
            **{
                k: v
                for k, v in run.detail.items()
                if k not in ("deliverables_error", "deliverables_said")
            },
            "deliverables": files,
            "formats": sorted({str(f["format"]) for f in files}),
            **done,
        }
    else:
        steps.add("render_failed", code=drawn.error, said=drawn.refusal)
        run.detail = {**run.detail, **drawn.detail(), **done}
    await session.commit()
    return {"drawn": [f["format"] for f in drawn.files], "error": drawn.error}


# ── its change, written again ───────────────────────────────────────────────


async def queue_change(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    """Its change to write again, for a worker: the model takes minutes."""
    return await queue_redraw(workspace_id, run_id, "code_change")


async def queue_redraw(workspace_id: uuid.UUID, run_id: uuid.UUID, renders: str) -> bool:
    """What LEKA draws of it — its change, its design — drawn again, for a
    worker: the model takes minutes."""
    job, word = REDRAWN[renders]
    queued = await enqueue_job(
        job,
        str(workspace_id),
        str(run_id),
        for_workspace_id=workspace_id,
        queue=JobQueue.HIGH,
        concurrency_key=f"agent-run-{word}:{run_id}",
    )
    return queued is not None


async def _read_again(
    session: AsyncSession, workspace_id: uuid.UUID, names: object
) -> dict[str, str]:
    """The files a run read (« owner/repo:path »), read again on their
    repository's default branch — those it cannot, left out."""
    # Here, not at the top: changes.py reads the catalogue, which reads the
    # registry, which reads the code tools' names.
    from leka.capabilities.changes import code_for
    from leka.connectors import CodeRefusedError

    read: dict[str, str] = {}
    opened: dict[str, tuple[Any, str] | None] = {}
    for name in names if isinstance(names, list) else []:
        repository, _, path = str(name).partition(":")
        if not path:
            continue
        if repository not in opened:
            found = await code_for(session, workspace_id, repository)
            opened[repository] = (
                (found[1], await found[1].default_branch(repository)) if found else None
            )
        reader = opened[repository]
        if reader is None:
            continue
        code, branch = reader
        try:
            text = await code.read(repository, path, branch)
        except CodeRefusedError:
            continue
        if text is not None:
            read[str(name)] = text
    return read


async def rewrite_change(workspace_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, object]:
    """A finished code-change run's change written again from the analysis it
    delivered and the files it read, read again — never the run done again
    (2026-10-18: its change was not written, the analysis alone shown).
    Whatever goes wrong, « being written » ends, said why."""
    return await redraw_render(workspace_id, run_id, "code_change")


async def redraw_design(workspace_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, object]:
    """A finished design review's mock-ups drawn again from the review it
    delivered — never the run done again (2026-10-18: a review came alone,
    its mock-ups not drawn)."""
    return await redraw_render(workspace_id, run_id, "design_mockups")


async def redraw_render(
    workspace_id: uuid.UUID, run_id: uuid.UUID, renders: str
) -> dict[str, object]:
    """What LEKA draws of a finished run, drawn again; whatever goes wrong,
    « being drawn » ends, said why."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            try:
                return await _redraw_render(session, workspace_id, run_id, renders)
            except Exception:
                logger.exception("run_change_not_written", run=str(run_id))
                await session.rollback()
                runs = CapabilityRunRepository(session, workspace_id)
                run = await runs.run(run_id, lock=True)
                if run is not None:
                    Steps(session, run, await runs.last_seq(run_id)).add(
                        "render_failed", code="error"
                    )
                    run.detail = {
                        **run.detail,
                        "drawing": None,
                        "drawing_since": None,
                        "deliverables_error": "error",
                    }
                    await session.commit()
                return {"proposed": None, "error": "error"}


async def _redraw_render(
    session: AsyncSession, workspace_id: uuid.UUID, run_id: uuid.UUID, renders: str
) -> dict[str, object]:
    runs = CapabilityRunRepository(session, workspace_id)
    run = await runs.run(run_id)
    done = {"drawing": None, "drawing_since": None}
    if run is None or run.status != RunStatus.SUCCEEDED or not run.output:
        return {"proposed": None, "skipped": "not_finished"}
    subject = await subject_of(session, workspace_id, run.requested_by)
    permissions = frozenset(p.value for p in subject.permissions) if subject else frozenset()
    entry = await CatalogueService(session, workspace_id).entry(run.key, permissions=permissions)
    if entry is None or entry.definition.renders != renders:
        run.detail = {**run.detail, **done}
        await session.commit()
        return {"proposed": None, "skipped": "not_drawn"}
    read = await _read_again(session, workspace_id, run.detail.get("read_files"))
    if not read:
        # A run from before its files were kept: those its report names.
        from leka.capabilities.changes import files_named

        read = await files_named(session, run, run.output)
    output = run.output
    # Nothing held while the model writes: minutes.
    await session.commit()
    drawn = await draw(session, run, entry.definition, output, read=read)
    run = await runs.run(run_id, lock=True)
    if run is None:
        return {"proposed": None, "skipped": "gone"}
    steps = Steps(session, run, await runs.last_seq(run_id))
    if drawn.error is None:
        steps.add(drawn.step, **drawn.said())
        run.detail = {
            **{
                k: v
                for k, v in run.detail.items()
                if k not in ("deliverables_error", "deliverables_said")
            },
            **drawn.detail(),
            **done,
        }
    else:
        steps.add("render_failed", code=drawn.error, said=drawn.refusal)
        run.detail = {**run.detail, **drawn.detail(), **done}
    await session.commit()
    return {
        "proposed": run.detail.get("code_change") or run.detail.get("design"),
        "error": drawn.error,
    }


async def queue_correction(
    workspace_id: uuid.UUID, run_id: uuid.UUID, target: str, note: str
) -> bool:
    """One mock-up to correct, for a worker: the model takes minutes."""
    queued = await enqueue_job(
        CORRECT_JOB,
        str(workspace_id),
        str(run_id),
        target,
        note,
        for_workspace_id=workspace_id,
        queue=JobQueue.HIGH,
        concurrency_key=f"agent-run-design:{run_id}",
    )
    return queued is not None


async def correct_design_run(
    workspace_id: uuid.UUID, run_id: uuid.UUID, target: str, note: str
) -> dict[str, object]:
    """A design review's mock-up corrected as asked — the rest as it was,
    the run never done again; whatever goes wrong, « being corrected »
    ends, said why."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            try:
                return await _correct_design(session, workspace_id, run_id, target, note)
            except Exception:
                logger.exception("run_design_not_corrected", run=str(run_id))
                await session.rollback()
                runs = CapabilityRunRepository(session, workspace_id)
                run = await runs.run(run_id, lock=True)
                if run is not None:
                    Steps(session, run, await runs.last_seq(run_id)).add(
                        "render_failed", code="error"
                    )
                    run.detail = {**run.detail, "correcting": None, "correction_failed": "error"}
                    await session.commit()
                return {"corrected": None, "error": "error"}


async def _correct_design(
    session: AsyncSession, workspace_id: uuid.UUID, run_id: uuid.UUID, target: str, note: str
) -> dict[str, object]:
    # Here, not at the top: mockups reads the catalogue's needs.
    from leka.capabilities.changes import files_named
    from leka.capabilities.mockups import correct_design

    runs = CapabilityRunRepository(session, workspace_id)
    run = await runs.run(run_id)
    if run is None or run.status != RunStatus.SUCCEEDED or not run.output:
        return {"corrected": None, "skipped": "not_finished"}
    subject = await subject_of(session, workspace_id, run.requested_by)
    permissions = frozenset(p.value for p in subject.permissions) if subject else frozenset()
    entry = await CatalogueService(session, workspace_id).entry(run.key, permissions=permissions)
    if entry is None or entry.definition.renders != "design_mockups":
        run.detail = {**run.detail, "correcting": None}
        await session.commit()
        return {"corrected": None, "skipped": "not_drawn"}
    read = await _read_again(session, workspace_id, run.detail.get("read_files"))
    if not read:
        read = await files_named(session, run, run.output)
    output = run.output
    # Nothing held while the model draws: minutes.
    await session.commit()
    designed = await correct_design(session, run, entry.definition, output, read, target, note)
    run = await runs.run(run_id, lock=True)
    if run is None:
        return {"corrected": None, "skipped": "gone"}
    steps = Steps(session, run, await runs.last_seq(run_id))
    if designed.kept is not None:
        steps.add("corrected", target=target, **designed.usage)
        had = run.detail.get("corrections")
        history = [h for h in (had if isinstance(had, list) else []) if isinstance(h, dict)]
        history.append({"target": target, "note": note[:300], "at": now_or().isoformat()})
        run.detail = {
            **run.detail,
            **designed.kept,
            "corrections": history[-20:],
            "correcting": None,
            "correction_failed": None,
            "correction_said": None,
        }
    else:
        steps.add("render_failed", code=designed.error, said=designed.refusal)
        run.detail = {
            **run.detail,
            "correcting": None,
            "correction_failed": designed.error or "error",
            "correction_said": designed.refusal,
        }
    await session.commit()
    return {"corrected": designed.kept is not None, "error": designed.error}


def correct_design_job(workspace_id: str, run_id: str, target: str, note: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(correct_design_run(uuid.UUID(workspace_id), uuid.UUID(run_id), target, note))


def rewrite_change_job(workspace_id: str, run_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(rewrite_change(uuid.UUID(workspace_id), uuid.UUID(run_id)))


def redraw_design_job(workspace_id: str, run_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(redraw_design(uuid.UUID(workspace_id), uuid.UUID(run_id)))


def draw_files(workspace_id: str, run_id: str, formats: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    wanted = [f for f in formats.split(",") if f in DECK_FILES]
    return asyncio.run(redraw(uuid.UUID(workspace_id), uuid.UUID(run_id), wanted))


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
