"""Facturation, over HTTP: what the workspace holds and did this month.

    GET /billing/usage      members, sources, the model's size; intentions,
                            analyses, capability runs and plans this month,
                            against last month
    GET /billing/credits    its plan, its AI credits this month — allowance,
                            used, left — and whether they are spent (LEKA-430)
    GET /billing/contract   an Enterprise contract: its type, the
                            organisation, since when, its members, its
                            dedicated contact — 404 on a public plan
    GET  /billing/credits/prompt
                            past 90 % or 100 % of the month's AI credits,
                            what the reader is offered (LEKA-527): the usage,
                            the next plan, its credits and price — null under
                            90 % or once put aside
    POST /billing/credits/prompt/dismiss
                            « Plus tard » / « Fermer »: that threshold, for
                            the reader, this month — 204
    POST /billing/credits/prompt/ask
                            one who may not change the plan asks its admins
                            to, once a month for each threshold

No payment nor invoice is held by LEKA yet: plans and packs are LEKA's to
give, by its server command; the page says how to ask.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.billing import ContractRead, contract_now
from leka.core.errors import ErrorCode
from leka.governance import Permission, Principal, require_permission
from leka.identity import User
from leka.intentions import WorkspaceUsageRead, workspace_usage
from leka.metering import (
    CreditPromptChoice,
    CreditPromptRead,
    CreditsRead,
    credit_prompt,
    credits_now,
    dismiss_credit_prompt,
)
from leka.notifications import ask_for_upgrade, upgrade_asked

router = APIRouter(prefix="/billing", tags=["billing"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]


@router.get("/usage", response_model=WorkspaceUsageRead)
async def usage(principal: Reader, session: SessionDep) -> WorkspaceUsageRead:
    return await workspace_usage(session, principal.workspace_id, now=datetime.now(UTC))


@router.get("/credits", response_model=CreditsRead)
async def ai_credits(principal: Reader, session: SessionDep) -> CreditsRead:
    return await credits_now(session, principal.workspace_id, now=datetime.now(UTC))


@router.get("/contract", response_model=ContractRead, summary="An Enterprise contract")
async def contract(principal: Reader, session: SessionDep) -> ContractRead:
    found = await contract_now(session, principal.workspace_id)
    if found is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No contract: a public plan."
        )
    return found


async def _prompt(session: SessionDep, principal: Principal) -> CreditPromptRead | None:
    found = await credit_prompt(
        session,
        principal.workspace_id,
        principal.user_id,
        # Who may pay: who may update the workspace (no billing permission).
        can_pay=principal.has(Permission.WORKSPACE_UPDATE),
        now=datetime.now(UTC),
    )
    if found is None or found.can_pay:
        return found
    asked = await upgrade_asked(
        session,
        principal.workspace_id,
        by=principal.user_id,
        threshold=found.threshold,
        period=found.period_start.date(),
    )
    return found.model_copy(update={"asked": asked})


@router.get("/credits/prompt", response_model=CreditPromptRead | None)
async def credits_prompt(principal: Reader, session: SessionDep) -> CreditPromptRead | None:
    """What the reader is offered as the month's AI credits run out (LEKA-527)."""
    found = await _prompt(session, principal)
    # The threshold kept once, its billing account made — whoever read first.
    await session.commit()
    return found


@router.post("/credits/prompt/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_prompt(body: CreditPromptChoice, principal: Reader, session: SessionDep) -> None:
    """Put aside by the reader: that threshold, this month — the next comes."""
    if not await dismiss_credit_prompt(
        session, principal.workspace_id, principal.user_id, body.threshold, now=datetime.now(UTC)
    ):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "No prompt at this threshold.",
        )
    await session.commit()


@router.post("/credits/prompt/ask", response_model=CreditPromptRead)
async def ask_admins(
    body: CreditPromptChoice, principal: Reader, session: SessionDep
) -> CreditPromptRead:
    """One who may not change the plan asks its admins to — told once."""
    found = await _prompt(session, principal)
    if found is None or found.threshold != body.threshold:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "No such prompt now.")
    if found.can_pay:
        raise ApiError(
            status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "You may change the plan yourself."
        )
    person = await session.get(User, principal.user_id)
    name = (person.first_name or person.email) if person is not None else ""
    await ask_for_upgrade(
        session,
        principal.workspace_id,
        by=principal.user_id,
        name=name,
        plan_key=found.recommended.key if found.recommended else None,
        plan_name=found.recommended.name if found.recommended else None,
        threshold=found.threshold,
        period=found.period_start.date(),
        now=datetime.now(UTC),
    )
    await session.commit()
    return found.model_copy(update={"asked": True})
