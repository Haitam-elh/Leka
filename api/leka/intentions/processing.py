"""An intention's analysis, run (LEKA-388): from its assembled context to a
result the decision interface reads — kept, and the intention moved on.

    asked, or asked again, or asked to analyse again
        ──▶ queue_analysis ──▶ intention-analysis:<id>  (one at a time)
    run_analysis:
        1. the intention, as understood, and its context's readiness
           (LEKA-387) — blocked: said, nothing run, it stays analysing
        2. the analysis recorded `running`, committed
        3. its context (the context engine's contract, LEKA-376) and the
           parts its capabilities read — each part read on its own: one
           that cannot be read skips what needs it, the rest goes on
        4. each capability chosen, isolated (analysis.execute)
        5. one result, kept with the analysis; the findings it rests on
           linked to the intention; the intention moved —
               a question answered      completed   (answered)
               a request on systems     awaiting_decision (proposed): a
                                        person decides (LEKA-390)
               nothing could run        failed
           — unless it moved on meanwhile (cancelled, asked again — its
           context the same id at a newer version): then the analysis is
           kept, said superseded, moves nothing, opens no decision

THE SWEEP (`run_pending_analyses`, every 15 minutes) says interrupted
what ran past its deadline — its intention failed, to be analysed again,
never left analysing (LEKA-443) — then runs what no job did: an intention
analysing whose context version has no analysis on its way or done — a
worker that died, a queue that was down.

Whatever raises while it runs is said failed, never left running
(LEKA-443); a person stopping it is said stopped — what it found kept,
never the intention's result.

Every analysis is a row (GET /intentions/{id}/analysis): which capabilities
and why, what each did — succeeded, failed, timed out, skipped — the
result, the error.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import enqueue_job
from leka.capabilities import (
    CatalogueService,
    ContextPack,
    LLMRuntime,
    SkillRuntime,
    permitted,
)
from leka.connectors import Source, SourceRepository, manifests
from leka.context import AssembledContext, ContextRepository, ContextService
from leka.db import hidden_entities, session_factory, system_scope, workspace_scope
from leka.governance import hidden_on_behalf
from leka.identity import spoken_language
from leka.ingestion import ContentRepository, ResolutionRepository
from leka.intelligence import IntelligenceRepository, QualityRepository, QualityService
from leka.intentions.analysis import (
    Answer,
    Asked,
    Capability,
    Evidence,
    FindingBrief,
    Material,
    Part,
    Result,
    SourceRef,
    StepOutcome,
    Subject,
    assemble,
    relevant,
    strength_of,
)
from leka.intentions.analysis import (
    select as choose,
)
from leka.intentions.analyst import NEEDS as ANALYST
from leka.intentions.analyst import answer as analyst_answer
from leka.intentions.approval import DecisionService
from leka.intentions.capabilities import CAPABILITIES
from leka.intentions.decisions import Target
from leka.intentions.dispatch import dispatch
from leka.intentions.explain import ContextRead, SourceState, explain
from leka.intentions.grounding import side
from leka.intentions.journey import ANALYSIS_DEADLINE
from leka.intentions.lifecycle import Actor
from leka.intentions.lifecycle import IntentionStatus as S
from leka.intentions.models import Intention, IntentionAnalysis
from leka.intentions.orchestration import plan as orchestrate
from leka.intentions.orchestration import run as run_plan
from leka.intentions.reads import in_environment, learned_between
from leka.intentions.recommend import as_mapping, recommend
from leka.intentions.repository import IntentionRepository
from leka.intentions.schemas import (
    ContextReadiness,
    IntentionAnalysisResult,
    Understanding,
)
from leka.intentions.service import IntentionService
from leka.intentions.understanding import unknown_names
from leka.intentions.writing import NEEDS as WRITING
from leka.intentions.writing import write
from leka.knowledge import (
    ChangeFootprint,
    Entity,
    EntityBrief,
    EntityRepository,
    EntityType,
    EvolutionRepository,
    GraphRepository,
    GraphService,
    IncidentDetail,
    KnowledgeService,
)

logger = structlog.get_logger(__name__)

ANALYSIS_JOB = "leka.intentions.processing.run_analysis"
# The period an intention says none of: the last month.
DEFAULT_PERIOD = timedelta(days=30)
# How far a dependency walk goes, how many incidents and changes are read.
DEPTH = 2
MAX_INCIDENTS = 10
MAX_CHANGES = 20
MAX_FINDINGS = 50
# What followed a change, to be said to have followed it (LEKA-378).
AFTER = timedelta(hours=72)
# The findings an analysis rests on, linked to the intention, at most.
LINKED = 10


def concurrency_key(intention_id: uuid.UUID) -> str:
    return f"intention-analysis:{intention_id}"


async def queue_analysis(
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    *,
    trigger: str,
    by: uuid.UUID | None = None,
) -> bool:
    """Queue its analysis; False when one is already queued or running."""
    run = await enqueue_job(
        ANALYSIS_JOB,
        str(workspace_id),
        str(intention_id),
        job_kwargs={"trigger": trigger, "by": str(by) if by else None},
        for_workspace_id=workspace_id,
        concurrency_key=concurrency_key(intention_id),
    )
    return run is not None


def run_analysis(
    workspace_id: str, intention_id: str, trigger: str = "created", by: str | None = None
) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(
        analyse_intention(
            uuid.UUID(workspace_id),
            uuid.UUID(intention_id),
            trigger=trigger,
            by=uuid.UUID(by) if by else None,
        )
    )


def run_pending_analyses() -> dict[str, int]:
    """Entry point for the schedule — and for whoever runs what waits."""
    return asyncio.run(analyse_pending())


async def analyse_pending(*, limit: int = 100) -> dict[str, int]:
    """The analyses past their deadline said interrupted (LEKA-443); then
    every intention analysing whose context version has no analysis on its
    way or done, analysed now. Idempotent."""
    interrupted = await interrupt_overdue(limit=limit)
    with system_scope():
        async with session_factory() as session:
            # A blocked analysis is not one: questions judged blocked before
            # they could be answered anyway are analysed now. Asked again,
            # its context keeps its id and takes a new version (LEKA-374):
            # what counts is an analysis of that version (LEKA-433) — an
            # intention kept before readiness had one matches its versionless
            # analysis, not the sweep again and again.
            analysed = (
                select(IntentionAnalysis.id)
                .where(
                    IntentionAnalysis.intention_id == Intention.id,
                    IntentionAnalysis.context_id == Intention.context_id,
                    IntentionAnalysis.context_version.is_not_distinct_from(
                        Intention.readiness["version"].as_integer()
                    ),
                    # Blocked, stopped by a person, or failed: none read it
                    # for this attempt (LEKA-443).
                    IntentionAnalysis.status.not_in(("blocked", "stopped", "failed")),
                )
                .exists()
            )
            rows = await session.execute(
                select(Intention.workspace_id, Intention.id)
                .where(
                    Intention.status == S.ANALYSING.value,
                    Intention.archived_at.is_(None),
                    ~analysed,
                )
                .order_by(Intention.status_changed_at)
                .limit(limit)
            )
            pending = rows.tuples().all()
    done = {"analysed": 0, "blocked": 0, "failed": 0, "interrupted": interrupted}
    for workspace_id, intention_id in pending:
        outcome = await analyse_intention(workspace_id, intention_id, trigger="sweep")
        status = str(outcome.get("status"))
        done[
            "blocked" if status == "blocked" else "failed" if status == "failed" else "analysed"
        ] += 1
    logger.info("intention_analyses_swept", **done)
    return done


# ── one analysis ─────────────────────────────────────────────────────────────


def asked_of(intention: Intention, understood: Understanding | None, now: datetime) -> Asked:
    """The intention, as the analysis reads it: what it wants, about what,
    when, where, within which constraints."""
    scope = understood.scope if understood is not None else None
    entities = scope.entities if scope is not None else (understood.entities if understood else [])
    period = scope.period if scope is not None else None
    since = period.since if period is not None else now - DEFAULT_PERIOD
    until = period.until if period is not None else now
    return Asked(
        id=intention.id,
        text=intention.text,
        mode=understood.mode if understood else "question",
        kind=(understood.kind if understood else None) or intention.kind or "general",
        goal=understood.goal.code if understood else (intention.goal or "unknown"),
        actions=tuple(
            (a.code, a.changes_systems) for a in (understood.actions if understood else [])
        ),
        action_targets={
            a.code: tuple(a.targets) for a in (understood.actions if understood else [])
        },
        subjects=tuple(
            Subject(
                id=e.entity_id,
                name=e.name,
                type=e.type,
                lifecycle=getattr(e, "lifecycle", None),
            )
            for e in entities
        ),
        since=since,
        until=until,
        environment=(scope.environments[0] if scope and scope.environments else None)
        or (understood.environment if understood else None),
        constraints=tuple(
            (c.kind, c.value, c.hard) for c in (scope.constraints if scope is not None else [])
        ),
        unknown=tuple(unknown_names(understood.text)) if understood and not entities else (),
    )


def result_of(result: Result) -> dict[str, object]:
    """The result, as it is kept and read (IntentionAnalysisResult)."""

    def note(n: object) -> dict[str, object] | None:
        return None if n is None else {"code": n.code, "text": n.text, "params": dict(n.params)}  # type: ignore[attr-defined]

    def ref(value: object) -> object:
        return str(value) if isinstance(value, uuid.UUID) else value

    said = IntentionAnalysisResult.model_validate(
        {
            "status": result.status,
            "summary": [note(n) for n in result.summary],
            "findings": [
                {
                    "id": s.id,
                    "capability": name,
                    "code": s.code,
                    "text": s.text,
                    "params": {k: ref(v) for k, v in s.params.items()},
                    "evidence": list(s.evidence),
                }
                for name, s in result.findings
            ],
            "causes": [
                {
                    "id": c.id,
                    "capability": name,
                    "code": c.code,
                    "label": c.label,
                    "basis": c.basis,
                    "why": c.why,
                    "confidence": c.confidence,
                    "ref_type": c.ref_type,
                    "ref_id": c.ref_id,
                    "params": {k: ref(v) for k, v in c.params.items()},
                    "evidence": list(c.evidence),
                    "strength": strength_of(c),
                }
                for name, c in result.causes
            ],
            "impact": [
                {"code": area.code, "items": [asdict(item) for item in area.items]}
                for area in result.impact
            ],
            "risk": result.risk,
            "risk_basis": note(result.risk_basis),
            "uncertainties": [note(n) for n in result.uncertainties],
            "missing": [note(n) for n in result.missing],
            "confidence": result.confidence,
            "support": [note(n) for n in result.support],
            "evidence": [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "label": e.label,
                    "ref_type": e.ref_type,
                    "ref_id": e.ref_id,
                    "sources": [asdict(s) for s in e.sources],
                    "records": list(e.records),
                    "origin": e.origin,
                    "confidence": e.confidence,
                    "detail": e.detail,
                    "at": e.at,
                    "params": dict(e.params),
                }
                for e in result.evidence
            ],
            "recommendations": [as_mapping(r) for r in result.recommendations],
            "answer": (
                {
                    "text": result.answer.text,
                    "points": [
                        {"text": p.text, "cites": list(p.cites)} for p in result.answer.points
                    ],
                    "caveats": list(result.answer.caveats),
                    "provider": result.answer.provider,
                    "model": result.answer.model,
                    "version": result.answer.version,
                }
                if result.answer is not None
                else None
            ),
            "explanation": result.explanation,
        }
    )
    return said.model_dump(mode="json")


def _contexts(session: AsyncSession, workspace_id: uuid.UUID) -> ContextService:
    return ContextService(
        ContextRepository(session, workspace_id),
        GraphService(GraphRepository(session, workspace_id)),
        content=ContentRepository(session, workspace_id),
        resolution=ResolutionRepository(session, workspace_id),
        sources=SourceRepository(session, workspace_id),
    )


async def _next_number(session: AsyncSession, intention_id: uuid.UUID) -> int:
    found = await session.scalar(
        select(func.max(IntentionAnalysis.number)).where(
            IntentionAnalysis.intention_id == intention_id
        )
    )
    return int(found or 0) + 1


async def analyse_intention(
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    *,
    trigger: str,
    by: uuid.UUID | None = None,
    now: datetime | None = None,
    capabilities: Sequence[Capability] = CAPABILITIES,
) -> dict[str, object]:
    """One analysis, end to end — seeing only what the person who asked may
    (LEKA-402): what their role may not see of the company model is left out
    of everything it reads."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            intention = await IntentionRepository(session, workspace_id).intention(intention_id)
            asker = intention.created_by if intention is not None else None
            hidden = await hidden_on_behalf(session, workspace_id, asker)
    with hidden_entities(hidden):
        return await _analyse_intention(
            workspace_id,
            intention_id,
            trigger=trigger,
            by=by,
            now=now,
            capabilities=capabilities,
        )


async def _analyse_intention(
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    *,
    trigger: str,
    by: uuid.UUID | None,
    now: datetime | None,
    capabilities: Sequence[Capability],
) -> dict[str, object]:
    moment = now or datetime.now(UTC)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            intention = await IntentionRepository(session, workspace_id).intention(intention_id)
            if intention is None:
                return {"status": "gone"}
            if intention.status != S.ANALYSING.value or intention.archived_at is not None:
                return {"status": "not_analysing", "intention_status": intention.status}
            understood = (
                Understanding.model_validate(intention.understanding)
                if intention.understanding
                else None
            )
            ready = (
                ContextReadiness.model_validate(intention.readiness)
                if intention.readiness
                else None
            )
            asked = asked_of(intention, understood, moment)
            # Whose question it is: LEKA reads for them, with what they may read.
            asker = intention.created_by
            # And answers them in their language (identity.spoken_language).
            asked = replace(asked, language=await spoken_language(session, asker, workspace_id))
            context_id = intention.context_id
            # The agent that does what it asks, started for them (dispatch.py)
            # — once. Its work is the answer's first word. In a session of
            # its own: whatever goes wrong there leaves this one whole.
            try:
                async with session_factory() as own:
                    mine = await IntentionRepository(own, workspace_id).intention(intention.id)
                    handed = await dispatch(own, workspace_id, mine) if mine else None
            except Exception:
                logger.warning(
                    "intention_dispatch_failed", intention=str(intention.id), exc_info=True
                )
                handed = None
            if handed is not None and handed.run_id is not None:
                asked = replace(asked, handed=handed.said())
                if ready is not None and ready.status == "blocked":
                    # An agent is at work on it: nothing to clarify first.
                    ready = ready.model_copy(update={"status": "limited"})
            version = ready.version if ready is not None else None
            row = IntentionAnalysis(
                workspace_id=workspace_id,
                id=uuid.uuid4(),
                intention_id=intention.id,
                number=await _next_number(session, intention.id),
                trigger=trigger,
                status="running",
                requested_by=by,
                context_id=context_id,
                context_version=version,
                intention_version=intention.version,
                readiness=ready.status if ready is not None else None,
                started_at=moment,
                selection=[],
                steps=[],
                detail={},
            )
            if ready is not None and ready.status == "blocked" and not asked.acting:
                # Judged before a question could be answered anyway (kept
                # as it was): answered now, what was in the way said.
                ready = ready.model_copy(update={"status": "limited"})
            if ready is not None and ready.status == "blocked":
                # An action whose context has something critical in the way:
                # nothing is run, and the person is asked to clarify — never
                # left analysing.
                row.status = "blocked"
                row.finished_at = moment
                row.error = "context_blocked"
                row.detail = {
                    "critical": [issue.model_dump(mode="json") for issue in ready.critical]
                }
                session.add(row)
                await IntentionService(IntentionRepository(session, workspace_id)).move(
                    intention.id,
                    S.NEEDS_CLARIFICATION,
                    actor=Actor.SYSTEM,
                    reason="What it acts on must be clear first.",
                    detail={
                        "analysis_id": str(row.id),
                        "critical": [issue.said for issue in ready.critical][:5],
                    },
                    now=moment,
                )
                await session.commit()
                return {"status": "blocked", "analysis": str(row.id)}
            # What the workspace turned off in its catalogue (LEKA-393).
            disabled = await CatalogueService(session, workspace_id).disabled()
            # Whether a model can write its answer here (LEKA-394).
            writes = await LLMRuntime(session, workspace_id).ready(WRITING)
            choices = choose(asked, capabilities, disabled=disabled, model=writes)
            row.selection = [asdict(choice) for choice in choices]
            session.add(row)
            await session.commit()
            analysis_id = row.id
        try:
            chosen = [
                c for c in capabilities if any(ch.chosen and ch.name == c.name for ch in choices)
            ]
            rules = [c for c in chosen if c.method == "rules"]
            # What a model writes, from what the rules found: after them.
            writers = [c for c in chosen if c.method == "model"]
            # One plan for all of them (LEKA-399): who waits on whom, in levels.
            the_plan = orchestrate(chosen)
            wants = frozenset(part for c in rules for part in c.reads)
            context = await _context(workspace_id, context_id, version)
            material = await _material(workspace_id, asked, context, wants, ready, moment)
            started = time.monotonic()
            outcomes: list[StepOutcome] = await run_plan(
                the_plan,
                {c.name: c for c in capabilities},
                material,
                side=side,
                started=started,
                fallbacks={c.name: c for c in capabilities},
            )
            for choice in choices:
                if not choice.chosen and choice.reason == "no_model":
                    outcomes.append(
                        StepOutcome(choice.name, choice.version, "skipped", reason="no_model")
                    )
            result = assemble(
                outcomes,
                readiness=ready.status if ready is not None else "limited",
                sources=len(context.sources) if context is not None else 0,
                contradictions=len(context.conflicts) if context is not None else 0,
                context_level=(
                    context.quality.level if context is not None and context.quality else None
                ),
                background=frozenset(c.name for c in rules if c.always),
            )
            # What LEKA proposes, apart from what it found (LEKA-389).
            result = replace(result, recommendations=recommend(result, asked, material.changes))
            for capability in writers:
                at = max(0, round((time.monotonic() - started) * 1000))
                outcome, answer, read = await _write(
                    workspace_id, capability, asked, result, context, moment, by=asker
                )
                # The conclusion: it reads what every capability before it said.
                outcomes.append(
                    replace(
                        outcome,
                        level=the_plan.step(capability.name).level,
                        started_ms=at,
                        handed=tuple(o.name for o in outcomes if o.status == "succeeded"),
                    )
                )
                if answer is not None:
                    result = answered(result, answer, read)
            # On what it rests, said (LEKA-441): the sources' state as it read.
            result = await _explained(
                workspace_id,
                result,
                asked,
                understood,
                outcomes,
                context,
                readiness=ready.status if ready is not None else "limited",
                now=moment,
                background=frozenset(c.name for c in rules if c.always),
                kinds=relevant(rules),
            )
            return await _finish(
                workspace_id,
                intention_id,
                analysis_id,
                asked,
                result,
                outcomes,
                context_id,
                moment,
                orchestrated=the_plan.said(),
            )
        except Exception as error:
            # Whatever went wrong, never left running: said failed — its
            # type kept for whoever diagnoses it — and the intention can be
            # analysed again (LEKA-443).
            logger.exception(
                "intention_analysis_crashed", intention=str(intention_id), analysis=str(analysis_id)
            )
            return await _crashed(workspace_id, intention_id, analysis_id, error)


# What became of the synthesis, by how its execution ended (LEKA-429).
WRITTEN_AS = {
    "invalid": ("failed", "ungrounded"),
    "no_model": ("failed", "no_model"),
    "timed_out": ("timed_out", "TimeoutError"),
    "failed": ("failed", "model_failed"),
}


def answered(result: Result, answer: Answer, read: Sequence[Evidence]) -> Result:
    """The result with its answer, and what the analyst read that the answer
    cites, as evidence. An answer resting on what was read is an answer:
    the analysis is complete, whatever the rules alone made of it."""
    held = {e.id for e in result.evidence}
    evidence = (*result.evidence, *(e for e in read if e.id not in held))
    status = (
        "complete"
        if result.status in ("inconclusive", "failed") and answer.points
        else result.status
    )
    return replace(result, answer=answer, evidence=evidence, status=status)


async def _write(
    workspace_id: uuid.UUID,
    capability: Capability,
    asked: Asked,
    result: Result,
    context: AssembledContext | None,
    now: datetime,
    *,
    by: uuid.UUID | None = None,
) -> tuple[StepOutcome, Answer | None, tuple[Evidence, ...]]:
    """The question answered by LEKA's analyst — a model reading what it
    needs through LEKA's reads (analyst.py, skills.py), with what the person
    who asked (`by`) may read, as their role is now; when no model this
    workspace reaches can use tools, or it gives nothing usable, the
    analysis said in words from what the rules found (writing.py). Or said
    why not. Every execution, its calls and its reads are kept, answered or
    not."""
    started = time.monotonic()

    def took() -> int:
        return max(0, round((time.monotonic() - started) * 1000))

    pack = ContextPack.of_context(context) if context is not None else ContextPack()
    read: tuple[Evidence, ...] = ()
    try:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                runtime = LLMRuntime(session, workspace_id)
                try:
                    answer: Answer | None = None
                    if await runtime.ready(ANALYST):
                        skills = SkillRuntime(
                            session,
                            workspace_id,
                            permissions=await permitted(session, workspace_id, by),
                            by=by,
                            caller="analyst",
                            ref=f"intention:{asked.id}",
                            now=now,
                        )
                        done, answer, read = await analyst_answer(
                            runtime, skills, asked, result, pack, now=now
                        )
                    if answer is None:
                        done, answer = await write(runtime, asked, result, pack)
                finally:
                    await session.commit()
    except Exception:
        logger.exception("analysis_answer_failed", intention_id=str(asked.id))
        return (
            StepOutcome(capability.name, capability.version, "failed", took(), error="error"),
            None,
            (),
        )
    if answer is None:
        status, error = WRITTEN_AS.get(done.status, ("failed", done.status))
        return (
            StepOutcome(capability.name, capability.version, status, took(), error=error),
            None,
            (),
        )
    return StepOutcome(capability.name, capability.version, "succeeded", took()), answer, read


async def _context(
    workspace_id: uuid.UUID, context_id: uuid.UUID | None, version: int | None
) -> AssembledContext | None:
    if context_id is None:
        return None
    async with session_factory() as session:
        try:
            return await _contexts(session, workspace_id).assembled(context_id, version=version)
        except Exception as error:
            logger.warning("intention_analysis_unread", part="context", error=type(error).__name__)
            return None


async def _part(name: Part, read: Awaitable[object]) -> object | None:
    """One part, read on its own: a failure skips what needs it."""
    try:
        return await read
    except Exception as error:
        logger.warning("intention_analysis_unread", part=name.value, error=type(error).__name__)
        return None


async def _material(
    workspace_id: uuid.UUID,
    asked: Asked,
    context: AssembledContext | None,
    wants: frozenset[Part],
    ready: ContextReadiness | None,
    now: datetime,
) -> Material:
    """What the capabilities chosen read: the context's elements, and each
    part they declared — each in its own session."""
    ids = [s.id for s in asked.subjects]
    read: dict[str, object] = {}
    parts: set[Part] = set()

    async def take(part: Part, reader: Awaitable[object]) -> None:
        value = await _part(part, reader)
        if value is not None:
            read[part.value] = value
            parts.add(part)

    async with session_factory() as session:
        graph = GraphService(GraphRepository(session, workspace_id))
        repository = EntityRepository(session, workspace_id)
        knowledge = KnowledgeService(repository)
        entities = await repository.by_ids(ids)
        if Part.STANDING in wants:
            await take(Part.STANDING, graph.standing(ids))
        if Part.OWNERS in wants:
            await take(Part.OWNERS, graph.owners(ids))
        if Part.RESPONSIBILITY in wants:
            await take(
                Part.RESPONSIBILITY,
                _each(entities, lambda entity: knowledge.responsibility(entity)),
            )
        if Part.DOWNSTREAM in wants:
            await take(
                Part.DOWNSTREAM,
                _each(
                    entities,
                    lambda entity: knowledge.dependencies(
                        entity.id,
                        direction="downstream",
                        depth=DEPTH,
                        environment=asked.environment,
                    ),
                ),
            )
        if Part.UPSTREAM in wants:
            await take(
                Part.UPSTREAM,
                _each(
                    entities,
                    lambda entity: knowledge.dependencies(
                        entity.id, direction="upstream", depth=DEPTH, environment=asked.environment
                    ),
                ),
            )
        if Part.IMPACT in wants:
            await take(Part.IMPACT, knowledge.impact(ids))
        if Part.INCIDENTS in wants:
            await take(Part.INCIDENTS, _incidents(knowledge, repository, entities, asked, now))
        if Part.CHANGES in wants:
            await take(Part.CHANGES, _changes(graph, ids, asked, now))
        if Part.EVOLUTION in wants:
            await take(
                Part.EVOLUTION,
                learned_between(
                    EvolutionRepository(session, workspace_id),
                    set(ids),
                    since=asked.since or now - DEFAULT_PERIOD,
                    until=asked.until or now,
                ),
            )
    async with session_factory() as session:
        if Part.FINDINGS in wants:
            await take(Part.FINDINGS, _findings(IntelligenceRepository(session, workspace_id), ids))
        if Part.QUALITY in wants:
            await take(
                Part.QUALITY, QualityService(QualityRepository(session, workspace_id)).of(ids)
            )
        sources = await _sources(session, workspace_id, entities)

    def got(part: Part, empty: object) -> Any:
        return read.get(part.value) or empty

    owners: Mapping[uuid.UUID, Sequence[EntityBrief]] = got(Part.OWNERS, {})
    return Material(
        asked=asked,
        now=now,
        readiness=ready.status if ready is not None else "limited",
        elements=tuple(context.elements) if context is not None else (),
        parts=frozenset(parts),
        standing=got(Part.STANDING, {}),
        owners={k: tuple(v) for k, v in owners.items()},
        responsibility=got(Part.RESPONSIBILITY, {}),
        downstream=got(Part.DOWNSTREAM, {}),
        upstream=got(Part.UPSTREAM, {}),
        impact=read.get(Part.IMPACT.value),  # type: ignore[arg-type]
        incidents=tuple(got(Part.INCIDENTS, ())),
        changes=tuple(got(Part.CHANGES, ())),
        findings=tuple(got(Part.FINDINGS, ())),
        evolution=tuple(got(Part.EVOLUTION, ())),
        quality=got(Part.QUALITY, {}),
        sources=sources,
    )


async def _each(
    entities: Mapping[uuid.UUID, Entity],
    read: Callable[[Entity], Awaitable[object | None]],
) -> dict[uuid.UUID, object]:
    """A read per subject the model holds, kept by its id."""
    found: dict[uuid.UUID, object] = {}
    for ident, entity in entities.items():
        value = await read(entity)
        if value is not None:
            found[ident] = value
    return found


async def _incidents(
    knowledge: KnowledgeService,
    repository: EntityRepository,
    entities: Mapping[uuid.UUID, Entity],
    asked: Asked,
    now: datetime,
) -> list[IncidentDetail]:
    """The incidents on its subjects in its period, each in detail — every
    one in the workspace when it names nothing: « what happened in
    production since yesterday » is about all of it."""
    seen: list[uuid.UUID] = []
    since = asked.since or now - DEFAULT_PERIOD
    until = asked.until or now
    for entity in entities.values() if entities else [None]:
        timeline = await knowledge.timeline(
            entity, since=since, until=until, kinds=[EntityType.INCIDENT], limit=MAX_INCIDENTS
        )
        for event in timeline.events:
            if event.kind == "incident_opened" and event.entity.id not in seen:
                seen.append(event.entity.id)
    found = await repository.by_ids(seen[:MAX_INCIDENTS])
    return [await knowledge.incident(found[i]) for i in seen[:MAX_INCIDENTS] if i in found]


async def _changes(
    graph: GraphService, ids: Sequence[uuid.UUID], asked: Asked, now: datetime
) -> list[ChangeFootprint]:
    """The changes around its subjects in its period, each with its
    footprint (LEKA-378) — every one in the workspace when it names
    nothing, in the environment it says."""
    seen: dict[uuid.UUID, ChangeFootprint] = {}
    arounds: list[uuid.UUID | None] = list(ids) or [None]
    for ident in arounds:
        found, _ = await graph.footprints(
            since=asked.since or now - DEFAULT_PERIOD,
            until=asked.until or now,
            limit=MAX_CHANGES,
            after=AFTER,
            around=ident,
        )
        for footprint in found:
            seen.setdefault(footprint.change.id, footprint)
    kept = [f for f in seen.values() if ids or in_environment(f.environment, asked.environment)]
    return list(kept)[:MAX_CHANGES]


async def _findings(
    repository: IntelligenceRepository, ids: Sequence[uuid.UUID]
) -> list[FindingBrief]:
    return [
        FindingBrief(
            id=f.id,
            code=f.code,
            category=f.category,
            severity=f.severity,
            statement=f.statement,
            subject_id=f.subject_id,
            subject_name=f.subject_name,
            first_seen_at=f.first_seen_at,
            params=dict(f.params or {}),
        )
        for f in await repository.about(ids, limit=MAX_FINDINGS)
    ]


async def _sources(
    session: AsyncSession, workspace_id: uuid.UUID, entities: Mapping[uuid.UUID, Entity]
) -> dict[uuid.UUID, tuple[SourceRef, ...]]:
    """Each subject's sources, by its provenance: for evidence its context
    does not hold."""
    rows = await session.execute(
        select(Source.id, Source.kind, Source.name).where(Source.workspace_id == workspace_id)
    )
    named = {ident: (kind.value, name) for ident, kind, name in rows.tuples().all()}
    found: dict[uuid.UUID, tuple[SourceRef, ...]] = {}
    for ident, entity in entities.items():
        said = (entity.provenance or {}).get("sources") or []
        refs: list[SourceRef] = []
        for item in said if isinstance(said, list) else []:
            try:
                source = uuid.UUID(str(item.get("source_id")))
            except (ValueError, AttributeError):
                continue
            kind, name = named.get(source, (None, None))
            refs.append(SourceRef(source, kind, name))
        found[ident] = tuple({r.id: r for r in refs}.values())
    return found


async def _explained(
    workspace_id: uuid.UUID,
    result: Result,
    asked: Asked,
    understood: Understanding | None,
    outcomes: Sequence[StepOutcome],
    context: AssembledContext | None,
    *,
    readiness: str,
    now: datetime,
    background: frozenset[str],
    kinds: frozenset[str] | None = None,
) -> Result:
    """The result with what it rests on — held to it (explain.py)."""
    ids = [s.source_id for s in context.sources] if context is not None else []
    states: dict[uuid.UUID, SourceState] = {}
    if ids:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                rows = (await session.scalars(select(Source).where(Source.id.in_(ids)))).all()
        states = {
            row.id: SourceState(
                status=str(row.status),
                sync_status=str(row.sync_status),
                health=str(row.health_status),
                last_synced_at=row.last_synced_at,
            )
            for row in rows
        }
    # Connected, never read: it may hold the answer — said as a limit
    # (LEKA-444), when it is of a kind the answer reads (LEKA-448).
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            never = await session.execute(
                select(Source.name, Source.kind).where(
                    Source.workspace_id == workspace_id,
                    Source.status.in_(("active", "degraded", "error")),
                    Source.last_synced_at.is_(None),
                    Source.id.not_in(ids),
                )
            )
    category = {m.key.value: m.category.value for m in manifests()}
    unread = [
        name
        for name, kind in never.tuples().all()
        if kinds is None or category.get(str(kind), "custom") in kinds
    ]
    read = (
        ContextRead(
            version=context.version,
            sources=[(s.source_id, s.kind, s.name, s.elements) for s in context.sources],
            conflicts=[c.model_dump(mode="json") for c in context.conflicts],
        )
        if context is not None
        else None
    )
    held, explanation = explain(
        result,
        asked,
        understood,
        outcomes,
        context=read,
        states=states,
        readiness=readiness,
        now=now,
        background=background,
        unread=unread,
    )
    return replace(held, explanation=explanation.model_dump(mode="json"))


async def _finish(
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    analysis_id: uuid.UUID,
    asked: Asked,
    result: Result,
    outcomes: Sequence[StepOutcome],
    context_id: uuid.UUID | None,
    moment: datetime,
    *,
    orchestrated: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """The result kept, with how its capabilities were orchestrated; the
    findings it rests on linked; the intention moved — unless it moved on
    meanwhile."""
    async with session_factory() as session:
        repository = IntentionRepository(session, workspace_id)
        row = await session.get(IntentionAnalysis, analysis_id)
        intention = await repository.intention(intention_id, lock=True)
        if row is None or intention is None:
            return {"status": "gone"}
        row.steps = [
            {
                "name": o.name,
                "version": o.version,
                "status": o.status,
                "duration_ms": o.duration_ms,
                "error": o.error,
                "reason": o.reason,
                "level": o.level,
                "started_ms": o.started_ms,
                "handed": list(o.handed),
                "degraded": list(o.degraded),
                "fallback_of": o.fallback_of,
            }
            for o in outcomes
        ]
        if orchestrated is not None:
            row.detail = {**row.detail, "orchestration": dict(orchestrated)}
        row.result = result_of(result)
        # Stopped by a person, or said interrupted while it ran (LEKA-443):
        # what it came to is kept, as what it was — never the intention's.
        ended = row.status if row.status != "running" else None
        row.finished_at = datetime.now(UTC)
        if ended is None:
            row.status = result.status
            failed = [o for o in outcomes if o.status in ("failed", "timed_out")]
            row.error = failed[0].error if result.status == "failed" and failed else None
        # Its context as it stands now: asked again meanwhile, the same id at
        # a newer version (LEKA-433) — this one is then superseded.
        current_version = (
            intention.readiness.get("version") if intention.readiness is not None else None
        )
        current = (
            ended is None
            and intention.status == S.ANALYSING.value
            and intention.archived_at is None
            and intention.context_id == context_id
            and row.context_version == current_version
            and (row.intention_version is None or row.intention_version == intention.version)
        )
        if not current:
            if ended is None:
                row.detail = {**row.detail, "superseded": True}
            await session.commit()
            return {"status": row.status, "analysis": str(analysis_id), "superseded": True}
        service = IntentionService(
            repository, findings=IntelligenceRepository(session, workspace_id)
        )
        # What it came to, in a line: the answer written, else the rules' own.
        summary = (
            result.answer.text
            if result.answer is not None
            else result.summary[0].text
            if result.summary
            else None
        )
        detail = {"analysis_id": str(analysis_id), "number": row.number, "status": result.status}
        if result.status == "failed":
            await service.move(
                intention_id,
                S.FAILED,
                actor=Actor.SYSTEM,
                reason="Its analysis could not run.",
                detail=detail | {"error": row.error},
                now=moment,
            )
        else:
            for evidence in [e for e in result.evidence if e.ref_type == "finding"][:LINKED]:
                if evidence.ref_id is not None:
                    await service.link(
                        intention_id, "finding", evidence.ref_id, actor=Actor.SYSTEM, now=moment
                    )
            await service.move(
                intention_id,
                S.AWAITING_DECISION if asked.acting else S.COMPLETED,
                actor=Actor.SYSTEM,
                detail=detail,
                summary=summary,
                now=moment,
            )
            if asked.acting:
                await _decide(
                    session, workspace_id, service, intention, asked, row, result, outcomes, moment
                )
        await session.commit()
    logger.info(
        "intention_analysed",
        intention=str(intention_id),
        status=result.status,
        findings=len(result.findings),
        causes=len(result.causes),
    )
    return {"status": result.status, "analysis": str(analysis_id)}


async def _fail_if_current(
    repository: IntentionRepository,
    intention: Intention,
    row: IntentionAnalysis,
    error: str,
    moment: datetime,
) -> None:
    """Its intention failed, when this analysis was the one it waited for:
    analysing, this version, started since it was — never one it moved on
    from."""
    if (
        intention.status != S.ANALYSING.value
        or intention.archived_at is not None
        or (row.intention_version is not None and row.intention_version != intention.version)
        or row.started_at < intention.status_changed_at
    ):
        return
    await IntentionService(repository).move(
        intention.id,
        S.FAILED,
        actor=Actor.SYSTEM,
        reason="Its analysis could not finish.",
        detail={
            "analysis_id": str(row.id),
            "number": row.number,
            "status": "failed",
            "error": error,
        },
        now=moment,
    )


async def _crashed(
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    analysis_id: uuid.UUID,
    error: BaseException,
) -> dict[str, object]:
    """An analysis that raised (LEKA-443): said failed, the error's type kept
    for whoever diagnoses it; its intention failed when it waited for it —
    to be analysed again."""
    moment = datetime.now(UTC)
    async with session_factory() as session:
        repository = IntentionRepository(session, workspace_id)
        intention = await repository.intention(intention_id, lock=True)
        row = await session.get(IntentionAnalysis, analysis_id, with_for_update=True)
        if row is None or intention is None:
            return {"status": "gone"}
        if row.status == "running":
            row.status = "failed"
            row.error = "crashed"
            row.finished_at = moment
            row.detail = {**row.detail, "crashed": type(error).__name__}
            await _fail_if_current(repository, intention, row, "crashed", moment)
        await session.commit()
    return {"status": "failed", "analysis": str(analysis_id), "error": "crashed"}


async def interrupt_overdue(*, now: datetime | None = None, limit: int = 100) -> int:
    """Analyses running past their deadline — a worker that died, a job lost
    (LEKA-443): said interrupted; their intention failed when it waited for
    one, to be analysed again — never left analysing. Idempotent."""
    moment = now or datetime.now(UTC)
    with system_scope():
        async with session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(
                            IntentionAnalysis.workspace_id,
                            IntentionAnalysis.id,
                            IntentionAnalysis.intention_id,
                        )
                        .where(
                            IntentionAnalysis.status == "running",
                            IntentionAnalysis.started_at < moment - ANALYSIS_DEADLINE,
                        )
                        .order_by(IntentionAnalysis.started_at)
                        .limit(limit)
                    )
                )
                .tuples()
                .all()
            )
    interrupted = 0
    for workspace_id, analysis_id, intention_id in rows:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                repository = IntentionRepository(session, workspace_id)
                intention = await repository.intention(intention_id, lock=True)
                row = await session.get(IntentionAnalysis, analysis_id, with_for_update=True)
                if row is None or row.status != "running":
                    continue
                row.status = "failed"
                row.error = "interrupted"
                row.finished_at = moment
                if intention is not None:
                    await _fail_if_current(repository, intention, row, "interrupted", moment)
                await session.commit()
                interrupted += 1
    if interrupted:
        logger.warning("intention_analyses_interrupted", count=interrupted)
    return interrupted


async def _decide(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    service: IntentionService,
    intention: Intention,
    asked: Asked,
    row: IntentionAnalysis,
    result: Result,
    outcomes: Sequence[StepOutcome],
    moment: datetime,
) -> None:
    """What it asks to do, put to a person's decision (LEKA-390) — linked to
    it, so its history says so; gated when what it rests on is missing or
    its context stale (LEKA-436)."""
    opened = await DecisionService(session, workspace_id).open(
        intention,
        actions=asked.actions,
        targets=[Target(s.id, s.name, s.type) for s in asked.subjects],
        action_targets=asked.action_targets,
        evidence={o.name: o.status for o in outcomes},
        readiness=(
            ContextReadiness.model_validate(intention.readiness)
            if intention.readiness is not None
            else None
        ),
        environment=asked.environment,
        constraints=asked.constraints,
        analysis_id=row.id,
        context_version=row.context_version,
        analysis_risk=result.risk,
        now=moment,
    )
    if opened is None:
        return
    decision = opened.decision
    await service.link(
        intention.id,
        "decision",
        decision.id,
        actor=Actor.SYSTEM,
        label=f"#{decision.number}",
        detail={
            "risk": decision.risk,
            "required_approvals": decision.required_approvals,
            "actions": [p["action"] for p in decision.proposals],
        },
        now=moment,
    )
