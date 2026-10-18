"""An intention deleted, whatever its status (LEKA-487) — by its asker, or by
someone who may approve.

    delete   what is on its way stopped first: its agent runs and plans not
             started cancelled, never run nor billed; its analysis stopped.
             Nothing still at work: gone at once — its analyses, decisions,
             plans, events and files with it. Something at work (an analysis,
             an agent, a workflow, an action on a real system): its deletion
             pending — out of every list, nothing more done on it — until
             the sweep.
    sweep    a pending deletion done once nothing works on it any more:
             no plan running, and GRACE past — longer than a run may last
             before the runs' own sweeps call it abandoned.

What the ledger needs stays: usage records, model calls, agent and workflow
runs carry its id without a key to it — the bill reads them, never the
intention.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import AgentRun, WorkflowRun
from leka.db import session_factory, system_scope, workspace_scope
from leka.intentions.models import (
    Intention,
    IntentionAnalysis,
    IntentionAttachment,
    IntentionPlan,
    IntentionPlanStep,
)
from leka.platform.storage import ObjectStoreError, object_store

logger = structlog.get_logger(__name__)

# Longer than any run may work before its sweep says it abandoned (agent
# runs: 30 min; workflow runs: 1 h).
GRACE = timedelta(hours=1, minutes=10)

Deleted = Literal["deleted", "pending"]


class NotYoursToDeleteError(Exception):
    """Only its asker, or who may approve, deletes it."""


async def _stop(session: AsyncSession, intention: Intention, now: datetime) -> bool:
    """What is on its way stopped; True while something still works on it."""
    at_work = False
    for analysis in await session.scalars(
        select(IntentionAnalysis).where(
            IntentionAnalysis.intention_id == intention.id, IntentionAnalysis.status == "running"
        )
    ):
        analysis.status = "stopped"
        analysis.detail = {**analysis.detail, "stopped_at": now.isoformat(), "deleted": True}
        at_work = True
    for run in await session.scalars(
        select(AgentRun).where(
            AgentRun.intention_id == intention.id,
            AgentRun.status.in_(("awaiting_approval", "queued", "running")),
        )
    ):
        # Queued: it never runs. Running: what it delivers is not kept.
        at_work = at_work or run.status == "running"
        run.status = "cancelled"
        run.finished_at = now
        run.detail = {**run.detail, "cancelled_by": "intention_deleted"}
    for flow in await session.scalars(
        select(WorkflowRun).where(
            WorkflowRun.intention_id == intention.id, WorkflowRun.status.in_(("queued", "running"))
        )
    ):
        if flow.status == "queued":
            flow.status = "cancelled"
        else:
            at_work = True
    for plan in await session.scalars(
        select(IntentionPlan).where(
            IntentionPlan.intention_id == intention.id,
            IntentionPlan.status.in_(("planned", "scheduled", "running")),
        )
    ):
        # What has not started never starts; a step at work on a real
        # system ends and is said (actions.py reads cancel_requested).
        for step in await session.scalars(
            select(IntentionPlanStep).where(
                IntentionPlanStep.plan_id == plan.id, IntentionPlanStep.status == "pending"
            )
        ):
            step.status = "cancelled"
        if plan.status == "running":
            plan.detail = {**plan.detail, "cancel_requested": True}
            at_work = True
        else:
            plan.status = "cancelled"
            plan.error = "cancelled"
    # Said before it may be deleted: the rows it cascades to are not updated after.
    await session.flush()
    return at_work


async def _erase(session: AsyncSession, intention: Intention) -> list[str]:
    """Gone, and all that hangs on it; the keys of its files' bytes, removed
    once the rows are."""
    keys = list(
        await session.scalars(
            select(IntentionAttachment.storage_key).where(
                IntentionAttachment.intention_id == intention.id
            )
        )
    )
    await session.delete(intention)
    return keys


async def _remove_bytes(keys: list[str]) -> None:
    for key in keys:
        try:
            await object_store().delete(key)
        except ObjectStoreError:
            # The row is gone; the store's purge walk finds the bytes.
            logger.warning("attachment_bytes_not_removed", key=key, exc_info=True)


async def delete(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    *,
    by: uuid.UUID,
    steward: bool,
    now: datetime | None = None,
) -> Deleted | None:
    """Deleted at once, or pending while something still works on it. None:
    no such intention here. Commits: the bytes go only once the rows did."""
    moment = now or datetime.now(UTC)
    intention = await session.scalar(
        select(Intention)
        .where(Intention.workspace_id == workspace_id, Intention.id == intention_id)
        .with_for_update()
    )
    if intention is None:
        return None
    if not steward and intention.created_by != by:
        raise NotYoursToDeleteError
    if intention.deletion_requested_at is not None:
        return "pending"
    if await _stop(session, intention, moment):
        intention.deletion_requested_at = moment
        # Archived too: every move, analysis and action already refuses one.
        intention.archived_at = intention.archived_at or moment
        await session.commit()
        return "pending"
    keys = await _erase(session, intention)
    await session.commit()
    await _remove_bytes(keys)
    return "deleted"


async def sweep(now: datetime | None = None) -> dict[str, int]:
    """Pending deletions done, once nothing works on them any more."""
    moment = now or datetime.now(UTC)
    done = 0
    keys: list[str] = []
    with system_scope():
        async with session_factory() as session:
            due = await session.scalars(
                select(Intention).where(
                    Intention.deletion_requested_at.is_not(None),
                    Intention.deletion_requested_at <= moment - GRACE,
                )
            )
            for intention in list(due):
                running = await session.scalar(
                    select(IntentionPlan.id).where(
                        IntentionPlan.intention_id == intention.id,
                        IntentionPlan.status == "running",
                    )
                )
                if running is not None:
                    continue
                with workspace_scope(intention.workspace_id):
                    keys += await _erase(session, intention)
                done += 1
            await session.commit()
    await _remove_bytes(keys)
    logger.info("intention_deletions_swept", deleted=done)
    return {"deleted": done}


def run_deletion_sweep() -> dict[str, int]:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(sweep())
