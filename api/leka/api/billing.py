"""Facturation, over HTTP: what the workspace holds and did this month.

    GET /billing/usage      members, sources, the model's size; intentions,
                            analyses, capability runs and plans this month,
                            against last month

No plan, payment nor invoice is held by LEKA yet: the page says so, and
shows what is real — the consumption.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from leka.api.dependencies import SessionDep
from leka.governance import Permission, Principal, require_permission
from leka.intentions import WorkspaceUsageRead, workspace_usage

router = APIRouter(prefix="/billing", tags=["billing"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]


@router.get("/usage", response_model=WorkspaceUsageRead)
async def usage(principal: Reader, session: SessionDep) -> WorkspaceUsageRead:
    return await workspace_usage(session, principal.workspace_id, now=datetime.now(UTC))
