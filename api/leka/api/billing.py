"""Facturation, over HTTP: what the workspace holds and did this month.

    GET /billing/usage      members, sources, the model's size; intentions,
                            analyses, capability runs and plans this month,
                            against last month
    GET /billing/credits    its plan, its AI credits this month — allowance,
                            used, left — and whether they are spent (LEKA-430)

No payment nor invoice is held by LEKA yet: plans and packs are LEKA's to
give, by its server command; the page says how to ask.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from leka.api.dependencies import SessionDep
from leka.governance import Permission, Principal, require_permission
from leka.intentions import WorkspaceUsageRead, workspace_usage
from leka.metering import CreditsRead, credits_now

router = APIRouter(prefix="/billing", tags=["billing"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]


@router.get("/usage", response_model=WorkspaceUsageRead)
async def usage(principal: Reader, session: SessionDep) -> WorkspaceUsageRead:
    return await workspace_usage(session, principal.workspace_id, now=datetime.now(UTC))


@router.get("/credits", response_model=CreditsRead)
async def ai_credits(principal: Reader, session: SessionDep) -> CreditsRead:
    return await credits_now(session, principal.workspace_id, now=datetime.now(UTC))
