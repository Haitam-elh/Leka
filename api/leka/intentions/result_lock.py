"""What LEKA found, kept from who has not the rights it asks (LEKA-499).

An analysis proposes agents; while what it takes is not had — a plan to
choose, agents to buy — its result is locked: the server sends its status,
its plan of analysis and the agents proposed, never what it found (its
summary, findings, causes, impact, risk, evidence, answer…). Hiding it in
the browser would not be enough: it never reaches it.

Never locked: in a demonstration (fictive data, its own path); once agents
were launched on it — the rights were had; with nothing to buy.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import AgentRun
from leka.intentions.models import IntentionAnalysis
from leka.intentions.offer import offer_for
from leka.intentions.schemas import (
    IntentionAnalysisRead,
    IntentionAnalysisResult,
    IntentionOfferRead,
)
from leka.platform.models import Workspace

Lock = Literal["plan_required", "agents_required"]


def lock_of(offer: IntentionOfferRead) -> Lock | None:
    """What the offer says is missing: a plan, else agents; None: nothing."""
    if not offer.lines:
        return None
    return (
        "plan_required" if any(line.kind == "plan" for line in offer.lines) else "agents_required"
    )


async def locks(
    session: AsyncSession, workspace_id: uuid.UUID, intention_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Lock]:
    """The intentions among these whose result is locked, and why."""
    ids = list(intention_ids)
    if not ids:
        return {}
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.demo:
        return {}
    launched = set(
        await session.scalars(
            select(AgentRun.intention_id).where(
                AgentRun.workspace_id == workspace_id, AgentRun.intention_id.in_(ids)
            )
        )
    )
    proposing = set(
        await session.scalars(
            select(IntentionAnalysis.intention_id).where(
                IntentionAnalysis.workspace_id == workspace_id,
                IntentionAnalysis.intention_id.in_(ids),
                IntentionAnalysis.result["proposal"].is_not(None),
            )
        )
    )
    found: dict[uuid.UUID, Lock] = {}
    for intention_id in proposing - launched:
        lock = lock_of(await offer_for(session, workspace_id, intention_id))
        if lock is not None:
            found[intention_id] = lock
    return found


def locked(read: IntentionAnalysisRead, lock: Lock) -> IntentionAnalysisRead:
    """The analysis as sent while locked: how it went and what it proposes —
    nothing it found."""
    if read.result is None:
        return read.model_copy(update={"locked": lock})
    kept = IntentionAnalysisResult(
        status=read.result.status,
        summary=[],
        findings=[],
        causes=[],
        impact=[],
        risk="unknown",
        risk_basis=None,
        uncertainties=[],
        missing=[],
        confidence=None,
        support=[],
        evidence=[],
        proposal=read.result.proposal,
    )
    return read.model_copy(update={"result": kept, "locked": lock, "detail": {}})
