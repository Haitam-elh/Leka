"""The AI capacity's prompts (LEKA-527): past 90 % and 100 % of a month's
AI credits, the application tells a workspace's people where it stands and
offers the plan that gives more — in a banner, never in the way.

    credit_prompt()   the prompt a person sees now, or None: the highest
                      threshold passed that they did not put aside — the
                      usage, what happens next, the plan they are on and the
                      one recommended, credits and price read from metering
                      and the catalogue, on the subscription's own cadence
    dismiss()         « Plus tard », « Fermer »: that threshold, for them,
                      this month and this allowance — the next still comes

Each threshold passed is kept once a month (credit_warnings, unique): two
requests at once keep one, a new month starts over. What a person put aside
is theirs, for the month and the allowance it was seen on: an upgrade that
lifts the allowance hides what no longer applies, and prompts again if the
new one runs low; a downgrade, or a contract changed, shows what now applies.
A plan bought is the plan paid and applied — the prompt never says the
credits are there before.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing import Catalogue, account_of, catalogue, launch_eligible, quote
from leka.core.config import settings
from leka.governance import plan_credits
from leka.metering.credits import credits_now, keep_passed
from leka.metering.models import CreditPromptDismissal
from leka.metering.schemas import CreditPlanRead, CreditPromptRead, CreditsRead

ENTERPRISE = "enterprise"


def prompts_at() -> list[int]:
    return sorted({int(t) for t in settings.credit_prompts if 0 < int(t) <= 100})


def _plan(
    offer: Catalogue,
    key: str,
    interval: str,
    *,
    monthly_credits: int | None,
    launch: bool,
    today: datetime,
) -> CreditPlanRead:
    """A plan, its credits and its price on `interval` — the year's only
    when it is sold yearly, else the month's: never a cadence it is not."""
    plan = offer.plan(key)
    if plan.monthly_price is None:
        return CreditPlanRead(
            key=plan.key,
            name=plan.name,
            credits=monthly_credits,
            self_service=plan.self_service,
            interval=None,
            monthly=None,
            list_monthly=None,
            charged=None,
        )
    on = "year" if interval == "year" and plan.annual else "month"
    priced = quote(plan, on, offer, today=today.date(), launch=launch, trial=False)  # type: ignore[arg-type]
    return CreditPlanRead(
        key=plan.key,
        name=plan.name,
        credits=monthly_credits,
        self_service=plan.self_service,
        interval=priced.interval,
        monthly=priced.monthly,
        list_monthly=priced.list_monthly,
        charged=priced.charged,
        discount=priced.discount,
        percent=priced.percent,
        for_months=priced.for_months,
    )


def _regular(plan: CreditPlanRead) -> int | None:
    """A month's price on its cadence once a launch offer is over: the
    year's with its discount, the month's list price."""
    if plan.monthly is None:
        return None
    return plan.list_monthly if plan.discount == "launch" else plan.monthly


def _next(offer: Catalogue, key: str, monthly_credits: int) -> str | None:
    """The plan after `key` in the catalogue's order that gives more credits
    a month — a contract's counting as more."""
    keys = [plan.key for plan in offer.plans]
    if key not in keys:
        return None
    for plan in offer.plans[keys.index(key) + 1 :]:
        if plan.ai_credits_per_month.contractual or plan_credits(plan.key) > monthly_credits:
            return plan.key
    return None


async def _dismissed(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, read: CreditsRead
) -> set[int]:
    return set(
        (
            await session.scalars(
                select(CreditPromptDismissal.threshold).where(
                    CreditPromptDismissal.workspace_id == workspace_id,
                    CreditPromptDismissal.user_id == user_id,
                    CreditPromptDismissal.period == read.period_start.date(),
                    CreditPromptDismissal.allowance == read.allowance,
                )
            )
        ).all()
    )


async def credit_prompt(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    can_pay: bool,
    now: datetime | None = None,
) -> CreditPromptRead | None:
    """The prompt a person sees now — None under 90 %, or once put aside."""
    moment = now or datetime.now(UTC)
    read = await credits_now(session, workspace_id, now=moment)
    passed = [t for t in prompts_at() if read.allowance > 0 and read.percent >= t]
    if not passed:
        return None
    # Kept once a month, whoever reads first — the schedule's watch keeps
    # them too; two at once keep one.
    await keep_passed(session, workspace_id, read, moment, passed)
    shown = [t for t in passed if t not in await _dismissed(session, workspace_id, user_id, read)]
    if not shown:
        return None
    offer = catalogue()
    account = await account_of(session, workspace_id)
    interval = account.interval or "month"
    # A contract: an Enterprise plan, or credits other than its plan's.
    contract = read.plan == ENTERPRISE or read.monthly != plan_credits(read.plan)
    current = _plan(
        offer, read.plan, interval, monthly_credits=read.monthly, launch=False, today=moment
    )
    key = None if contract else _next(offer, read.plan, read.monthly)
    recommended = None
    if key is not None:
        contractual = offer.plan(key).ai_credits_per_month.contractual
        recommended = _plan(
            offer,
            key,
            interval,
            monthly_credits=None if contractual else plan_credits(key),
            launch=launch_eligible(account, offer, key, interval, moment.date()),  # type: ignore[arg-type]
            today=moment,
        )
    path: Literal["upgrade", "sales", "contract"] = (
        "contract"
        if recommended is None
        else "upgrade"
        if recommended.self_service and recommended.monthly is not None
        else "sales"
    )
    # What it adds a month, as each is billed on this cadence for good —
    # never a launch offer's months taken for the price.
    more_monthly = None
    regular = None if recommended is None else _regular(recommended)
    if (
        recommended is not None
        and regular is not None
        and recommended.interval == (current.interval or recommended.interval)
    ):
        more_monthly = regular - (_regular(current) or 0)
    return CreditPromptRead(
        threshold=max(shown),
        used=read.used,
        allowance=read.allowance,
        remaining=read.remaining,
        percent=read.percent,
        period_start=read.period_start,
        period_end=read.period_end,
        enforced=read.enforced,
        current=current,
        recommended=recommended,
        more_credits=(
            recommended.credits - read.monthly
            if recommended is not None and recommended.credits is not None
            else None
        ),
        more_monthly=more_monthly,
        currency=offer.currency,
        path=path,
        contact_url=settings.sales_contact_url,
        can_pay=can_pay,
    )


async def dismiss(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    threshold: int,
    *,
    now: datetime | None = None,
) -> bool:
    """A prompt put aside by its reader — that threshold only, this month,
    this allowance. False: no such prompt to put aside."""
    if threshold not in prompts_at():
        return False
    moment = now or datetime.now(UTC)
    read = await credits_now(session, workspace_id, now=moment)
    await session.execute(
        insert(CreditPromptDismissal)
        .values(
            workspace_id=workspace_id,
            id=uuid.uuid4(),
            user_id=user_id,
            period=read.period_start.date(),
            threshold=threshold,
            allowance=read.allowance,
            at=moment,
        )
        .on_conflict_do_nothing(constraint="uq_credit_prompt_dismissals_once")
    )
    return True


__all__ = ["credit_prompt", "dismiss", "prompts_at"]
