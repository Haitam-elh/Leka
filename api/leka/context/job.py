"""Contexts keeping up with the company model (LEKA-374).

    a build that changed something ──▶ event "knowledge.model_built"
                                   ──▶ run_follow_for_event ──▶ context:<workspace>
    follow_workspace()
        1. what the builds since the last pass changed, said on each context
           it touches — it is behind, and on what (ContextService.follow_model)
        2. the contexts behind that follow the model and are in use, made
           again — each in its own transaction: one that fails is logged,
           stays behind, and the others go on

An EVENT, not a call: leka.knowledge must not import this module
(architecture rule 1), so the build publishes what happened and
leka/background/routes.py routes it here. One pass at a time per
workspace: the event's job is queued under one concurrency key. It is safe
to run twice — each build is followed once, a change told twice is one.

THE SWEEP, hourly (leka/background/schedule.py), queues a pass for each
workspace with contexts that follow the model: what an event lost, what a
pass left to the next (MAX_FOLLOWED). And it forgets the checks past
CHECK_DAYS — the versions keep what made them.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import Event, enqueue_job
from leka.connectors import SourceRepository
from leka.context.repository import ContextRepository, ContextSweeper
from leka.context.service import ContextService
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import ContentRepository, ResolutionRepository
from leka.knowledge import GraphRepository, GraphService

logger = structlog.get_logger(__name__)

FOLLOW_JOB = "leka.context.job.run_follow"
# How long a check is kept: what triggered each recalculation.
CHECK_DAYS = 90
# Workspaces one sweep queues at most; the next hour takes the rest.
SWEEP_BATCH = 200


def concurrency_key(workspace_id: uuid.UUID) -> str:
    return f"context:{workspace_id}"


def run_follow_for_event(event_id: str) -> str:
    """`knowledge.model_built` (leka/background/routes.py): queue a pass."""
    return asyncio.run(_queue_for_event(uuid.UUID(event_id)))


async def _queue_for_event(event_id: uuid.UUID) -> str:
    with system_scope():
        async with session_factory() as session:
            event = await session.get(Event, event_id)
    if event is None:
        return "gone"
    return "queued" if await _queue(event.workspace_id) else "already queued"


async def _queue(workspace_id: uuid.UUID) -> bool:
    """Queue the workspace's pass; False when one is already queued or running."""
    run = await enqueue_job(
        FOLLOW_JOB,
        str(workspace_id),
        for_workspace_id=workspace_id,
        concurrency_key=concurrency_key(workspace_id),
    )
    return run is not None


def run_follow(workspace_id: str) -> dict[str, int]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(follow_workspace(uuid.UUID(workspace_id)))


def _service(session: AsyncSession, workspace_id: uuid.UUID) -> ContextService:
    return ContextService(
        ContextRepository(session, workspace_id),
        GraphService(GraphRepository(session, workspace_id)),
        content=ContentRepository(session, workspace_id),
        resolution=ResolutionRepository(session, workspace_id),
        sources=SourceRepository(session, workspace_id),
    )


async def follow_workspace(
    workspace_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, int]:
    """One pass: what the model changed, said; what is due, made again."""
    now = now or datetime.now(UTC)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = _service(session, workspace_id)
            told = await service.follow_model(now=now)
            await session.commit()
            due = await service.due(now=now)
        counts = {**told, "version": 0, "unchanged": 0, "failed": 0, "errors": 0}
        for context_id in due:
            async with session_factory() as session:
                try:
                    outcome = await _service(session, workspace_id).follow_one(context_id)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    logger.exception("context_follow_failed", context_id=str(context_id))
                    counts["errors"] += 1
                    continue
            if outcome is not None and outcome.check is not None:
                counts[outcome.check.outcome] += 1
    logger.info("contexts_kept_up", workspace_id=str(workspace_id), **counts)
    return counts


def run_context_sweep() -> dict[str, int]:
    """Entry point for the schedule (leka/background/schedule.py)."""
    return asyncio.run(sweep_contexts())


async def sweep_contexts(*, now: datetime | None = None) -> dict[str, int]:
    """A pass queued for each workspace whose contexts follow the model;
    old checks forgotten. Idempotent."""
    now = now or datetime.now(UTC)
    with system_scope():
        async with session_factory() as session:
            sweeper = ContextSweeper(session)
            pruned = await sweeper.prune_checks(before=now - timedelta(days=CHECK_DAYS))
            followed = await sweeper.followed(SWEEP_BATCH)
            await session.commit()
    result = {"pruned": pruned, "queued": 0, "already_active": 0}
    for workspace_id in followed:
        result["queued" if await _queue(workspace_id) else "already_active"] += 1
    logger.info("contexts_swept", **result)
    return result
