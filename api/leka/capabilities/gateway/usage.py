"""What a workspace asked of language models (LEKA-394, 406, 430), read
from model_calls — what was recorded, nothing estimated twice:

    model_calls()   the latest calls, for its AI governance: for one person,
                    one run — never shown with their tokens or cost
                    (LEKA-530: those are the LEKA team's, internal —
                    python -m leka.metering.cli usage)
    leka_cost()     what its work cost LEKA since a moment, for its AI
                    credits and its controls
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.models import ModelCall


async def model_calls(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    limit: int = 100,
) -> Sequence[ModelCall]:
    """The latest calls, for audit (LEKA-406): for one person, one run."""
    query = (
        select(ModelCall)
        .where(ModelCall.workspace_id == workspace_id)
        .order_by(ModelCall.at.desc(), ModelCall.id)
        .limit(limit)
    )
    if user_id is not None:
        query = query.where(ModelCall.user_id == user_id)
    if run_id is not None:
        # An agent run's calls are about it by their ref (LEKA-395).
        query = query.where(or_(ModelCall.run_id == run_id, ModelCall.ref == f"agent_run:{run_id}"))
    return (await session.scalars(query)).all()


async def leka_costs(
    session: AsyncSession, workspace_ids: Sequence[uuid.UUID], *, since: datetime
) -> dict[uuid.UUID, float]:
    """leka_cost() of many workspaces at once (LEKA-558), the same calls
    counted; a workspace with none, 0."""
    if not workspace_ids:
        return {}
    spent = (
        await session.execute(
            select(ModelCall.workspace_id, func.coalesce(func.sum(ModelCall.cost_usd), 0.0))
            .where(
                ModelCall.workspace_id.in_(workspace_ids),
                ModelCall.at >= since,
                ModelCall.owner == "leka",
                ModelCall.status != "failed",
            )
            .group_by(ModelCall.workspace_id)
        )
    ).tuples()
    found = {workspace: float(cost or 0.0) for workspace, cost in spent}
    return {w: found.get(w, 0.0) for w in workspace_ids}


async def leka_cost(session: AsyncSession, workspace_id: uuid.UUID, *, since: datetime) -> float:
    """What the workspace's work cost LEKA since then, at the rates in force
    (LEKA-430): the calls to LEKA's models that answered — a failed one is
    not billed, a workspace's own model is its own account."""
    spent = await session.scalar(
        select(func.coalesce(func.sum(ModelCall.cost_usd), 0.0)).where(
            ModelCall.workspace_id == workspace_id,
            ModelCall.at >= since,
            ModelCall.owner == "leka",
            ModelCall.status != "failed",
        )
    )
    return float(spent or 0.0)
