"""What an intention costs to carry through, here (LEKA-458): the agents its
analysis proposed, as this workspace may run each; the AI capacity it will
take; the least plan that carries it; what is paid each month, the launch
offer and what is paid after — said before anything is consented to.

    agents     each proposed agent: included in its plan, owned (an option
               active), to buy (its monthly price), or unavailable and why —
               never shown included when it is not (LEKA-454)
    capacity   what this month has used — measured — and what the agents
               chosen will take — an estimate, from what they cost here
               before: none until they ran once
    plan       the least plan that carries it, cheapest first: one that
               runs agents when some are chosen, whose AI capacity left
               holds the estimate; the current plan when it does, Enterprise
               (by contract) when none does
    lines      the plan to subscribe to, then the options to buy — a sold
               bundle when it costs less than its agents one by one — each
               monthly, renewed until cancelled; the launch offer on the
               plan when it applies, with the price after it
    blocked    the month's capacity spent: why, and the plan that holds more
               — never an overage (LEKA-446)

Prices are the catalogue's (LEKA-454), never written here. It reads; it buys
nothing: what it says is what checkout charges, once consented to.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing import account_of, catalogue, launch_eligible, owned, quote
from leka.core.config import settings
from leka.intentions.feasibility import credits_left
from leka.intentions.models import IntentionAnalysis
from leka.intentions.schemas import (
    AgentProposalRead,
    IntentionOfferRead,
    OfferAgentRead,
    OfferLineRead,
    OfferPlanRead,
)

PLANS = ("free", "starter", "growth", "business", "enterprise")


def _plan_read(key: str, *, today_launch: bool, today: datetime) -> OfferPlanRead:
    offer = catalogue()
    plan = offer.plan(key)
    quotas = plan.quotas
    monthly = launch_monthly = None
    for_months = None
    trial_days = None
    if plan.monthly_price is not None and plan.self_service and plan.monthly_price > 0:
        priced = quote(plan, "month", offer, today=today.date(), launch=today_launch)
        monthly = priced.list_monthly
        if priced.discount == "launch":
            launch_monthly, for_months = priced.monthly, priced.for_months
        trial_days = priced.trial_days
    return OfferPlanRead(
        key=plan.key,
        name=plan.name,
        monthly_price=monthly if plan.monthly_price else plan.monthly_price,
        launch_monthly=launch_monthly,
        launch_months=for_months,
        trial_days=trial_days,
        credits=int(settings.plan_credits.get(plan.key, 0)) or None,
        users=quotas.users,
        sources=quotas.sources,
        analyses=quotas.analyses,
        runs_agents=PLANS.index(plan.key) >= PLANS.index(offer.add_ons.minimum_plan),
        contractual=plan.monthly_price is None,
    )


async def _proposal(
    session: AsyncSession, workspace_id: uuid.UUID, intention_id: uuid.UUID
) -> AgentProposalRead | None:
    """What its latest analysis proposed."""
    row = await session.scalar(
        select(IntentionAnalysis)
        .where(
            IntentionAnalysis.workspace_id == workspace_id,
            IntentionAnalysis.intention_id == intention_id,
            IntentionAnalysis.result.is_not(None),
        )
        .order_by(IntentionAnalysis.number.desc())
        .limit(1)
    )
    said = (row.result or {}).get("proposal") if row is not None else None
    return AgentProposalRead.model_validate(said) if said else None


async def offer_for(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    *,
    chosen: Sequence[str] | None = None,
    now: datetime | None = None,
) -> IntentionOfferRead:
    """What it takes here, for the agents chosen — every one proposed and
    available when none is said."""
    moment = now or datetime.now(UTC)
    offer = catalogue()
    sold = offer.add_ons
    proposal = await _proposal(session, workspace_id, intention_id)
    has = await owned(session, workspace_id)
    month = await credits_left(session, workspace_id, now=moment)
    account = await account_of(session, workspace_id)

    agents: list[OfferAgentRead] = []
    for agent in proposal.agents if proposal else []:
        why = has.why(agent.key)
        if has.every or agent.key in has.included:
            status = "included"
        elif why is None:
            status = "owned"
        elif why in ("not_owned", "plan_required") and agent.key in sold.agents:
            status = "to_buy"
        else:
            status = "unavailable"
        # What else keeps it from running here, its sources above all.
        blocking = [r for r in agent.reasons if r not in ("not_owned", "plan_required")]
        if blocking and status != "unavailable":
            status = "unavailable"
        agents.append(
            OfferAgentRead(
                key=agent.key,
                title=agent.title,
                category=agent.category,
                tier=sold.agents[agent.key].tier if agent.key in sold.agents else None,
                monthly_price=sold.prices.get(agent.key),
                status=status,
                reasons=blocking or ([why] if status == "unavailable" and why else []),
                credits=agent.credits,
                chosen=False,
            )
        )
    wanted = (
        {a.key for a in agents if a.status != "unavailable"}
        if chosen is None
        else {k for k in chosen if any(a.key == k and a.status != "unavailable" for a in agents)}
    )
    agents = [a.model_copy(update={"chosen": a.key in wanted}) for a in agents]
    picked = [a for a in agents if a.chosen]

    # The capacity: this month's, measured; the agents', estimated from
    # what they cost here — said unknown until each ran once.
    known = [a.credits for a in picked if a.credits is not None]
    estimate = round(sum(known), 2) if known else None
    estimate_complete = bool(picked) and len(known) == len(picked)

    current = month.plan
    needs_agents = any(a.status in ("to_buy", "owned") for a in picked) and not has.every

    def enough(key: str) -> bool:
        plan = _plan_read(key, today_launch=False, today=moment)
        if plan.contractual:
            return True
        if needs_agents and not plan.runs_agents:
            return False
        total = plan.credits or 0
        left = total - month.used
        return estimate is None or left >= estimate

    start = PLANS.index(current) if current in PLANS else 0
    recommended = next((p for p in PLANS[start:] if enough(p)), "enterprise")
    # The month's capacity spent, the plan enforcing it: blocked — the next
    # plan holds more; never an overage, never capacity sold apart.
    blocked = "credits_exhausted" if month.state == "exhausted" and month.enforced else None
    if blocked and recommended == current and current in PLANS[:-1]:
        recommended = PLANS[PLANS.index(current) + 1]
    eligible = (
        launch_eligible(account, offer, recommended, "month", moment.date())
        if (recommended not in ("free", "enterprise"))
        else False
    )
    plan = _plan_read(recommended, today_launch=eligible, today=moment)
    change = recommended != current

    lines: list[OfferLineRead] = []
    if change and not plan.contractual and plan.monthly_price:
        lines.append(
            OfferLineRead(
                kind="plan",
                key=plan.key,
                label=plan.name,
                monthly_price=plan.launch_monthly or plan.monthly_price,
                then_monthly=plan.monthly_price if plan.launch_monthly else None,
                for_months=plan.launch_months,
            )
        )
    to_buy = [a for a in picked if a.status == "to_buy"]
    alone = sum(a.monthly_price or 0 for a in to_buy)
    bundle = next(
        (
            b
            for b in sold.bundles
            if b.sellable
            and to_buy
            and {a.key for a in to_buy} <= set(b.agents)
            and b.monthly_price < alone
        ),
        None,
    )
    if bundle is not None:
        lines.append(
            OfferLineRead(
                kind="bundle",
                key=bundle.key,
                label=bundle.name.fr,
                monthly_price=bundle.monthly_price,
                agents=list(bundle.agents),
            )
        )
    else:
        lines.extend(
            OfferLineRead(
                kind="agent",
                key=a.key,
                label=a.title,
                monthly_price=a.monthly_price or 0,
                agents=[a.key],
            )
            for a in to_buy
        )
    total = sum(line.monthly_price for line in lines)
    then = sum(line.then_monthly or line.monthly_price for line in lines)

    return IntentionOfferRead(
        plan_now=current,
        plan=plan,
        change_plan=change,
        agents=agents,
        lines=lines,
        total_monthly=total,
        then_monthly=then if then != total else None,
        used=month.used,
        allowance=month.allowance,
        estimate=estimate,
        estimate_complete=estimate_complete,
        blocked=blocked,
        ready=not lines and not blocked and not (change and plan.contractual),
        provisional=sold.provisional,
    )
