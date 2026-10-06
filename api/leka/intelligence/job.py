"""The intelligence engine's jobs (LEKA-377): when LEKA analyses, and how.

    the model built ──▶ event "knowledge.model_built"
                    ──▶ run_intelligence_for_event ──▶ intelligence:<workspace>
    someone asks    ──▶ POST /intelligence/runs    ──▶ the same queue
    the sweep       ──▶ hourly                     ──▶ the same queue

    run_intelligence: a run, recorded `running`, committed — then its
    material read, each part in its own session — then each analysis,
    isolated, its outcome kept in its own transaction — then the run
    finished: succeeded, partial, failed.

One run at a time per workspace: one concurrency key. A second ask while
one is queued or running is not an error — that one will answer.

ISOLATION, three times over. An analysis that raises, or exceeds its
budget, is its step's failure (analysis.execute). A step whose findings
cannot be written is rolled back alone and recorded failed in a fresh
session. A part of the material that cannot be read skips the analyses
that need it. Only an error outside all three — the run itself cannot be
started — fails the job, and the background loop retries it (ADR 013).

OBSERVABLE: every run and step is a row (GET /intelligence/runs), every
failure a log line with the run and the analysis — and the background
job's own run id (`job_run_id`), so "the run" and "the worker's logs" are
one search.

THE SWEEP, hourly (leka/background/schedule.py), queues what no event
will: a workspace whose model was built before this module existed, a run
that failed, a new analysis or version, a day without a run — contexts
fall behind with time, not only with builds. It closes runs a dead worker
left, forgets runs past HISTORY_DAYS — never a workspace's latest — and
findings resolved past RESOLVED_DAYS.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import Event, enqueue_job
from leka.background.runner import RQ_JOB_TIMEOUT
from leka.context import ContextRepository
from leka.db import session_factory, system_scope, workspace_scope
from leka.intelligence.analysis import (
    Analyzer,
    Authority,
    ContextStanding,
    Material,
    Reads,
    catalogue_hash,
    execute,
)
from leka.intelligence.repository import IntelligenceRepository, IntelligenceSweeper
from leka.intelligence.rules import ANALYZERS
from leka.intelligence.service import IntelligenceService, ModelRead
from leka.knowledge import (
    AssertionRepository,
    ChangeFootprint,
    Dispute,
    GraphRepository,
    GraphService,
    queue_model_build,
)

logger = structlog.get_logger(__name__)

INTELLIGENCE_JOB = "leka.intelligence.job.run_intelligence"
HISTORY_DAYS = 90
RESOLVED_DAYS = 365
# A workspace not analysed for this long is analysed again.
REFRESH = timedelta(hours=24)
# Longer than RQ lets a job's work-horse live: a run older than this is dead.
STUCK_AFTER = timedelta(seconds=RQ_JOB_TIMEOUT) + timedelta(hours=1)
# Runs one sweep queues at most; the next hour takes the rest.
SWEEP_BATCH = 200


def concurrency_key(workspace_id: uuid.UUID) -> str:
    return f"intelligence:{workspace_id}"


async def queue_run(
    workspace_id: uuid.UUID,
    *,
    trigger: str,
    by: uuid.UUID | None = None,
    analyzers: Sequence[str] = (),
) -> bool:
    """Queue a run; False when one is already queued or running."""
    run = await enqueue_job(
        INTELLIGENCE_JOB,
        str(workspace_id),
        job_kwargs={
            "trigger": trigger,
            "by": str(by) if by else None,
            "analyzers": list(analyzers),
        },
        for_workspace_id=workspace_id,
        concurrency_key=concurrency_key(workspace_id),
    )
    return run is not None


def run_intelligence_for_event(event_id: str) -> str:
    """`knowledge.model_built` (leka/background/routes.py): queue a run."""
    return asyncio.run(_queue_for_event(uuid.UUID(event_id)))


async def _queue_for_event(event_id: uuid.UUID) -> str:
    with system_scope():
        async with session_factory() as session:
            event = await session.get(Event, event_id)
    if event is None:
        return "gone"
    queued = await queue_run(event.workspace_id, trigger="model")
    return "queued" if queued else "already queued"


def run_intelligence(
    workspace_id: str,
    trigger: str = "request",
    by: str | None = None,
    analyzers: list[str] | None = None,
) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(
        analyse_workspace(
            uuid.UUID(workspace_id),
            trigger=trigger,
            by=uuid.UUID(by) if by else None,
            names=analyzers or (),
        )
    )


def _service(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    analyzers: Sequence[Analyzer] = ANALYZERS,
) -> IntelligenceService:
    return IntelligenceService(
        IntelligenceRepository(session, workspace_id),
        GraphService(GraphRepository(session, workspace_id)),
        ContextRepository(session, workspace_id),
        analyzers=analyzers,
        assertions=AssertionRepository(session, workspace_id),
    )


def _job_run_id() -> uuid.UUID | None:
    """The background run this job is, from its logs' context (the runner
    binds it): what links our run to job_runs."""
    bound = structlog.contextvars.get_contextvars().get("run_id")
    try:
        return uuid.UUID(str(bound)) if bound else None
    except ValueError:
        return None


async def analyse_workspace(
    workspace_id: uuid.UUID,
    *,
    trigger: str,
    by: uuid.UUID | None = None,
    names: Sequence[str] = (),
    analyzers: Sequence[Analyzer] = ANALYZERS,
    now: datetime | None = None,
) -> dict[str, object]:
    """One run, end to end."""
    clock = now
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = _service(session, workspace_id, analyzers)
            chosen = service.chosen(names)
            run = await service.start(
                trigger=trigger,
                requested=list(names),
                by=by,
                job_run_id=_job_run_id(),
                now=clock or datetime.now(UTC),
            )
            await session.commit()
            run_id, built_at = run.id, run.model_built_at
        moment = clock or datetime.now(UTC)
        model = await _model(workspace_id, chosen, moment)
        disputes = await _disputes(workspace_id, chosen)
        material = Material(
            now=moment,
            built_at=built_at,
            architecture=model.architecture if model else None,
            owners=model.owners if model else {},
            standing=model.standing if model else {},
            documents=model.documents if model else None,
            categories=model.categories if model else {},
            owned_by=model.owned_by if model else {},
            memberships=model.memberships if model else {},
            disputes=disputes[0] if disputes else None,
            authority=disputes[1] if disputes else (),
            contexts=await _contexts(workspace_id, chosen, moment),
            changes=await _changes(workspace_id, chosen, moment),
        )
        for analyzer in chosen:
            outcome = await execute(analyzer, material)
            at = clock or datetime.now(UTC)
            async with session_factory() as session:
                try:
                    await _service(session, workspace_id, analyzers).record(
                        run_id, analyzer, outcome, material, now=at
                    )
                    await session.commit()
                    continue
                except Exception as error:
                    await session.rollback()
                    logger.exception(
                        "intelligence_step_unrecorded", run=str(run_id), analyzer=analyzer.name
                    )
                    failure = type(error).__name__
            async with session_factory() as session:
                await _service(session, workspace_id, analyzers).record_failure(
                    run_id, analyzer, failure, now=at
                )
                await session.commit()
        async with session_factory() as session:
            finished = await _service(session, workspace_id, analyzers).finish(
                run_id, now=clock or datetime.now(UTC)
            )
            await session.commit()
    if int(finished.counts.get("by_policy", 0) or 0):
        # Facts the policy accepted (LEKA-380): the model applies them.
        await queue_model_build(workspace_id)
    return {"run": str(run_id), "status": finished.status, **finished.counts}


async def _model(
    workspace_id: uuid.UUID, analyzers: Sequence[Analyzer], now: datetime
) -> ModelRead | None:
    if not any(Reads.MODEL in analyzer.wants for analyzer in analyzers):
        return None
    async with session_factory() as session:
        try:
            return await _service(session, workspace_id).read_model(now=now)
        except Exception as error:
            # One part unread is not the run lost.
            logger.warning("intelligence_material_unread", part="model", error=type(error).__name__)
            return None


async def _disputes(
    workspace_id: uuid.UUID, analyzers: Sequence[Analyzer]
) -> tuple[tuple[Dispute, ...], tuple[Authority, ...]] | None:
    if not any(Reads.CONFLICTS in analyzer.wants for analyzer in analyzers):
        return None
    async with session_factory() as session:
        try:
            return await _service(session, workspace_id).read_disputes()
        except Exception as error:
            # One part unread is not the run lost.
            logger.warning(
                "intelligence_material_unread", part="conflicts", error=type(error).__name__
            )
            return None


async def _contexts(
    workspace_id: uuid.UUID, analyzers: Sequence[Analyzer], now: datetime
) -> tuple[ContextStanding, ...] | None:
    if not any(Reads.CONTEXT in analyzer.wants for analyzer in analyzers):
        return None
    async with session_factory() as session:
        try:
            return await _service(session, workspace_id).read_contexts(now=now)
        except Exception as error:
            logger.warning(
                "intelligence_material_unread", part="context", error=type(error).__name__
            )
            return None


async def _changes(
    workspace_id: uuid.UUID, analyzers: Sequence[Analyzer], now: datetime
) -> tuple[ChangeFootprint, ...] | None:
    if not any(Reads.CHANGES in analyzer.wants for analyzer in analyzers):
        return None
    async with session_factory() as session:
        try:
            return await _service(session, workspace_id).read_changes(now=now)
        except Exception as error:
            # One part unread is not the run lost.
            logger.warning(
                "intelligence_material_unread", part="changes", error=type(error).__name__
            )
            return None


def run_intelligence_sweep() -> dict[str, int]:
    """Entry point for the schedule (leka/background/schedule.py)."""
    return asyncio.run(sweep_intelligence())


async def sweep_intelligence(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace whose analysis is behind, queued; dead runs closed;
    old history forgotten. Idempotent."""
    now = now or datetime.now(UTC)
    catalogue = catalogue_hash(ANALYZERS)
    with system_scope():
        async with session_factory() as session:
            sweeper = IntelligenceSweeper(session)
            abandoned = await sweeper.abandon_stuck(before=now - STUCK_AFTER, at=now)
            pruned = await sweeper.prune_runs(before=now - timedelta(days=HISTORY_DAYS))
            forgotten = await sweeper.prune_resolved(before=now - timedelta(days=RESOLVED_DAYS))
            standings = await sweeper.standings()
            await session.commit()
    behind = [
        standing.workspace_id
        for standing in standings
        if standing.analysed_at is None
        or standing.catalogue != catalogue
        or (standing.built_at is not None and standing.analysed_built_at != standing.built_at)
        or now - standing.analysed_at >= REFRESH
    ]
    result = {
        "abandoned": abandoned,
        "pruned": pruned,
        "forgotten": forgotten,
        "queued": 0,
        "already_active": 0,
    }
    for workspace_id in behind[:SWEEP_BATCH]:
        queued = await queue_run(workspace_id, trigger="schedule")
        result["queued" if queued else "already_active"] += 1
    logger.info("intelligence_swept", **result)
    return result
