"""What it takes to carry an intention through (LEKA-439): the capabilities it
needs, whether this workspace may use each — its plan, its credits, what is
connected, who asks — and, when it cannot, the least it takes to.

    the capabilities   what the router sends it to (LEKA-398) — LEKA's own
                       analysis always — for this person, as the catalogue
                       stands; each said
                         included     LEKA's own analysis, and the agents
                                      its plan includes (Karim, 2026-10-15)
                         beta         an agent while it is not on sale:
                                      usable, its future price said
                                      (decided 2026-10-13)
                         add_on       an agent on sale — every one since
                                      2026-10-14: bought, from Starter
                         planned      not ready yet: never offered as usable
                       and, usable or not here, why: a source to connect, a
                       language model, a permission, turned off
    the credits        this month's (metering, LEKA-430): what is left, what
                       an agent of that kind has cost here (the median of its
                       runs), whether LEKA's models stop when they are spent
    the verdict        ready · prerequisites (something to connect or allow
                       first) · over_quota (credits spent, or too few) ·
                       impossible (what it expects, nothing LEKA has makes)
    the path           the least it takes, cheapest first: what to connect or
                       allow; an add-on, or a bundle when it costs less than
                       its agents one by one — or the plan that includes
                       them, when it costs less (LEKA-462); the cheapest plan
                       whose AI capacity is enough — never the dearest by
                       default, and
                       never a capacity pack: none is sold (LEKA-446);
                       Enterprise by contract. Anything bought is consented
                       to first: nothing here buys.

It reads; it never changes anything.
"""

from __future__ import annotations

import statistics
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing import BillingAccount
from leka.billing.catalogue import Catalogue, quote
from leka.billing.catalogue import catalogue as billing_catalogue
from leka.capabilities import AgentRun, CatalogueService, ModelCall, find, leka_cost
from leka.capabilities.definition import Availability, Definition, Kind, Lifecycle
from leka.capabilities.router import Routing, route
from leka.core.config import settings
from leka.governance import allowance, credits_of, next_month
from leka.intentions.models import Intention
from leka.intentions.routing import query_of
from leka.intentions.schemas import CreditsLeftRead, IntentionBrief, Understanding

# What an agent's past runs say of its cost: those of the last 90 days.
HISTORY = timedelta(days=90)
# Below this, a median says too little.
FEW = 1
PLANS = ("free", "starter", "growth", "business", "enterprise")
# What a capability that makes a document says it delivers.
DOCUMENT = "document"


@dataclass(frozen=True)
class Needed:
    """One capability it needs, as this workspace may use it."""

    key: str
    title: str
    kind: str
    offer: str  # included, beta, add_on, planned
    available: bool
    reasons: tuple[Mapping[str, object], ...]  # why not, code and detail
    delivers: str  # finding, analysis, document, proposal
    selected: bool  # routed to, or always run
    credits: float | None  # what one run of it has cost here, median
    price: int | None = None  # an add-on's monthly price, cents
    # What it is routed to: without it, it is not carried through. What
    # always runs with an analysis (a model's synthesis) only adds to it.
    essential: bool = True


@dataclass(frozen=True)
class Step:
    """One thing it takes, cheapest first."""

    kind: str  # connect_source, ask_admin, configure_model, enable,
    # buy_add_on, buy_bundle, change_plan, contact_sales, rephrase
    detail: Mapping[str, object] = field(default_factory=dict)
    # It costs money or changes a plan: never done without a yes.
    consent: bool = False


@dataclass(frozen=True)
class Feasibility:
    verdict: str  # ready, prerequisites, over_quota, impossible
    needed: tuple[Needed, ...]
    credits: CreditsLeftRead
    estimate: float | None  # what carrying it through should cost, credits
    path: tuple[Step, ...]


def offer_of(
    definition: Definition, sold: Catalogue, included: Collection[str] = frozenset()
) -> str:
    """How LEKA offers it: included, beta, add_on or planned — `included`,
    the agents the workspace's plan includes."""
    if definition.lifecycle in (Lifecycle.DRAFT, Lifecycle.REVIEW):
        return "planned"
    if definition.kind is Kind.WORKFLOW:
        offers = {
            offer_of(step, sold, included)
            for step in _steps(definition)
            if step is not None and step.kind is not Kind.WORKFLOW
        }
        for worst in ("planned", "add_on", "beta"):
            if worst in offers:
                return worst
        return "included"
    if definition.kind is not Kind.AGENT:
        return "included"
    if definition.key in included:
        return "included"
    # Not its plan's: on sale, bought; until then, beta.
    on_sale = sold.add_ons.available and definition.key in sold.add_ons.agents
    return "add_on" if on_sale else "beta"


def _steps(definition: Definition) -> list[Definition | None]:
    return [find(key) for key in definition.uses]


def _reasons(availability: Availability) -> tuple[Mapping[str, object], ...]:
    return tuple({"code": r.code, **r.detail} for r in availability.reasons)


# What each reason it cannot run here takes — something to connect or allow
# first. Without a step: it cannot be made to run here.
FIXES: Mapping[str, str] = {
    "missing_source": "connect_source",
    "no_model": "configure_model",
    "not_permitted": "ask_admin",
    "disabled": "enable",
}


def needed_of(
    routing: Routing,
    entries: Mapping[str, tuple[Definition, Availability]],
    sold: Catalogue,
    costs: Mapping[str, float],
    included: Collection[str] = frozenset(),
) -> list[Needed]:
    """What it needs: what it is routed to, and what always runs."""
    keys: list[str] = [c.key for c in routing.selected]
    for key in (*routing.background, routing.fallback):
        if key and key not in keys:
            keys.append(key)
    # Matched, but not usable here: said, so what it takes can be. Eligible
    # but not chosen, what makes a document: what a document asks for.
    keys += [c.key for c in routing.excluded if c.key not in keys and c.eligible]
    keys += [
        c.key
        for c in routing.candidates
        if c.key not in keys and c.eligible and c.definition.contract.output == DOCUMENT
    ]
    found: list[Needed] = []
    for key in keys:
        entry = entries.get(key)
        if entry is None:
            continue
        definition, availability = entry
        offer = offer_of(definition, sold, included)
        found.append(
            Needed(
                key=key,
                title=definition.title,
                kind=definition.kind.value,
                offer=offer,
                available=availability.available and offer != "planned",
                reasons=_reasons(availability),
                delivers=definition.contract.output,
                selected=key in {c.key for c in routing.selected}
                or key in routing.background
                or key == routing.fallback,
                credits=costs.get(key),
                price=sold.add_ons.prices.get(key) if offer == "add_on" else None,
                essential=key in {c.key for c in routing.selected},
            )
        )
    return found


def _plan_enough(sold: Catalogue, plan_credits: Mapping[str, int], need: float) -> str | None:
    """The cheapest self-service plan whose credits a month cover `need`."""
    for plan in sold.plans:
        if plan.self_service and plan_credits.get(plan.key, 0) >= need:
            return plan.key
    return None


def path_of(
    needed: Sequence[Needed],
    month: CreditsLeftRead,
    estimate: float | None,
    sold: Catalogue,
    plan_credits: Mapping[str, int],
    *,
    expected: str,
    launch: bool = True,
) -> tuple[str, tuple[Step, ...]]:
    """The verdict, and the least it takes — cheapest first."""
    used = [n for n in needed if n.selected]
    if expected == DOCUMENT and not any(n.delivers == DOCUMENT for n in needed):
        # Nothing LEKA has makes what it expects: said, never promised.
        return "impossible", (Step("rephrase", {"expected": expected}),)
    steps: list[Step] = []
    blocked = [n for n in used if n.essential and not n.available]
    makes = [n for n in needed if n.delivers == DOCUMENT] if expected == DOCUMENT else []
    if makes and not any(n.available for n in makes):
        blocked += [n for n in makes if n not in blocked]
    for n in blocked:
        if n.offer == "planned":
            continue
        for reason in n.reasons:
            fix = FIXES.get(str(reason.get("code")))
            if fix is not None:
                steps.append(Step(fix, {"capability": n.key, **reason}))
    if makes and all(n.offer == "planned" for n in makes):
        return "impossible", (Step("rephrase", {"expected": expected, "planned": True}),)

    # What it pays for (2026-10-14): a plan that runs agents first, then
    # those it does not own — never one it already has.
    def paid(n: Needed) -> set[str]:
        return {str(r.get("code")) for r in n.reasons} & {"plan_required", "not_owned"}

    current = month.plan
    # The plan it must move to, if any: the highest any need asks for.
    target: str | None = None
    why = "agents"
    if any("plan_required" in paid(n) for n in used):
        target = sold.add_ons.minimum_plan
    wanted = sorted({n.key for n in used if n.offer == "add_on" and paid(n)})
    bought = _bought(wanted, sold) if wanted else []
    covering = _plan_including(sold, wanted, above=current) if wanted else None
    # The least it costs a month (LEKA-462): its agents bought, or the plan
    # that includes them — never the dearer of the two.
    if covering is not None:
        alone = _monthly(sold, _higher(target, current)) + sum(
            p for step in bought if isinstance(p := step.detail.get("monthly_price"), int)
        )
        if _monthly(sold, covering) < alone:
            target, bought = covering, []
    short = month.state == "exhausted" or (estimate is not None and month.remaining < estimate)
    sales = False
    if short:
        # A month that is enough: what it used and what it needs.
        need = month.used + (estimate or 1)
        enough = _plan_enough(sold, plan_credits, need)
        if enough is not None and PLANS.index(enough) > PLANS.index(current):
            target = _higher(target, enough)
            if target == enough:
                why = "credits"
            # The plan the credits ask for may include what was to be bought.
            if wanted and set(wanted) <= sold.add_ons.included_in(target):
                bought = []
        else:
            sales = True
    if target is not None and PLANS.index(target) > PLANS.index(current):
        steps.append(_plan_step(sold, plan_credits, target, month, why=why, launch=launch))
    steps += bought
    if sales:
        steps.append(Step("contact_sales", {"plan": "enterprise"}))
    if short:
        return "over_quota", tuple(steps)
    if steps:
        return "prerequisites", tuple(steps)
    return "ready", ()


def _monthly(sold: Catalogue, plan: str) -> int:
    return sold.plan(plan).monthly_price or 0


def _higher(plan: str | None, other: str) -> str:
    return other if plan is None or PLANS.index(other) > PLANS.index(plan) else plan


def _plan_including(sold: Catalogue, agents: Sequence[str], *, above: str) -> str | None:
    """The cheapest self-service plan above `above` that includes `agents`."""
    for plan in sold.plans:
        if (
            plan.self_service
            and PLANS.index(plan.key) > PLANS.index(above)
            and set(agents) <= sold.add_ons.included_in(plan.key)
        ):
            return plan.key
    return None


def _plan_step(
    sold: Catalogue,
    plan_credits: Mapping[str, int],
    key: str,
    month: CreditsLeftRead,
    *,
    why: str,
    launch: bool,
) -> Step:
    """A move to `key`, said in full before any yes (LEKA-462): its price
    excl. VAT a month, the launch offer when this workspace may have it and
    for how long, then what it renews at, every month until cancelled; its
    credits and the agents it includes."""
    priced = quote(sold.plan(key), "month", sold, today=month.period_end.date(), launch=launch)
    detail: dict[str, object] = {
        "plan": key,
        "monthly_price": priced.list_monthly,
        "credits": plan_credits.get(key),
        "why": why,
        "interval": "month",
        "renews": True,
        "includes": sorted(sold.add_ons.included_in(key)),
    }
    if priced.discount == "launch":
        detail |= {
            "launch_percent": priced.percent,
            "launch_months": priced.for_months,
            "launch_price": priced.monthly,
            "then_price": priced.then_monthly,
        }
    return Step("change_plan", detail, consent=True)


def _bought(add_ons: Sequence[str], sold: Catalogue) -> list[Step]:
    """Specialist agents on sale: a bundle when it costs less than them one
    by one, else each."""
    wanted = set(add_ons)
    alone = sum(sold.add_ons.prices.get(key, 0) for key in add_ons)
    priced = all(key in sold.add_ons.prices for key in add_ons)
    bundles = sorted(
        (b for b in sold.add_ons.bundles if b.sellable and wanted <= set(b.agents)),
        key=lambda b: b.monthly_price,
    )
    if bundles and (not priced or bundles[0].monthly_price < alone):
        best = bundles[0]
        return [
            Step(
                "buy_bundle",
                {
                    "bundle": best.key,
                    "agents": list(best.agents),
                    "monthly_price": best.monthly_price,
                    "renews": True,
                },
                consent=True,
            )
        ]
    return [
        Step(
            "buy_add_on",
            {"agent": key, "monthly_price": sold.add_ons.prices.get(key), "renews": True},
            consent=True,
        )
        for key in add_ons
    ]


async def credits_left(
    session: AsyncSession, workspace_id: uuid.UUID, *, now: datetime
) -> CreditsLeftRead:
    """This month's AI credits, read as metering reads them (LEKA-430,
    `metering.credits.credits_now`) from what both stand on — the plan's
    allowance (governance) and what LEKA's models cost (capabilities): the
    intentions sit below metering, never on it. The two agree, tested."""
    given = await allowance(session, workspace_id, now)
    start = datetime.combine(given.period, time.min, tzinfo=UTC)
    used = round(credits_of(await leka_cost(session, workspace_id, since=start)), 2)
    total = given.credits
    percent = round(used / total * 100, 1) if total else (100.0 if used else 0.0)
    thresholds = sorted({int(t) for t in settings.credit_warnings if 0 < int(t) <= 100})
    state = (
        "exhausted"
        if used >= total
        else "warning"
        if thresholds and percent >= thresholds[0]
        else "ok"
    )
    return CreditsLeftRead(
        plan=given.plan.name,
        allowance=total,
        used=used,
        remaining=round(max(total - used, 0.0), 2),
        state=state,
        enforced=settings.credits_enforced,
        period_end=datetime.combine(next_month(given.period), time.min, tzinfo=UTC),
    )


async def run_costs(
    session: AsyncSession, keys: Sequence[str], *, now: datetime
) -> dict[str, float]:
    """What one run of each agent has cost this workspace, in credits: the
    median of its runs that finished, LEKA's models only."""
    if not keys:
        return {}
    rows = await session.execute(
        select(AgentRun.key, func.sum(ModelCall.cost_usd))
        .join(ModelCall, ModelCall.run_id == AgentRun.id)
        .where(
            AgentRun.key.in_(list(keys)),
            AgentRun.status == "succeeded",
            AgentRun.queued_at >= now - HISTORY,
            ModelCall.owner == "leka",
            ModelCall.cost_usd.is_not(None),
        )
        .group_by(AgentRun.id, AgentRun.key)
    )
    per: dict[str, list[float]] = {}
    for key, cost in rows.tuples().all():
        if cost is not None:
            per.setdefault(key, []).append(credits_of(float(cost)))
    return {key: round(statistics.median(v), 2) for key, v in per.items() if len(v) >= FEW}


async def feasibility_of(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    understanding: Understanding,
    brief: IntentionBrief,
    *,
    permissions: frozenset[str],
    now: datetime,
    sold: Catalogue | None = None,
    plan_credits: Mapping[str, int] | None = None,
) -> Feasibility:
    """What it takes to carry it through, for this person in this workspace."""
    from leka.governance.plans import plan_credits as credits_for

    sold = sold or billing_catalogue()
    entries = {
        e.definition.key: (e.definition, e.availability)
        for e in await CatalogueService(session, workspace_id).entries(permissions=permissions)
    }
    # The router reads an intention: one made of what was understood.
    asked = Intention(id=uuid.uuid4(), text=understanding.text, goal=understanding.goal.code)
    routing = route(
        query_of(asked, understanding, None),
        [d for d, _ in entries.values()],
        {key: availability for key, (_, availability) in entries.items()},
    )
    agents = [key for key, (d, _) in entries.items() if d.kind is Kind.AGENT]
    costs = await run_costs(session, agents, now=now)
    month = await credits_left(session, workspace_id, now=now)
    needed = needed_of(routing, entries, sold, costs, sold.add_ons.included_in(month.plan))
    spends = [n.credits for n in needed if n.selected and n.credits is not None]
    estimate = round(sum(spends), 2) if spends else None
    expected = next((s.value for s in brief.slots if s.slot == "expected"), "answer") or "answer"
    allowances = plan_credits or {plan: credits_for(plan) for plan in PLANS}
    # The launch offer is had once (billing): never promised again after.
    used_offer = await session.scalar(
        select(BillingAccount.launch_offer_used).where(BillingAccount.workspace_id == workspace_id)
    )
    verdict, path = path_of(
        needed, month, estimate, sold, allowances, expected=expected, launch=not used_offer
    )
    return Feasibility(
        verdict=verdict, needed=tuple(needed), credits=month, estimate=estimate, path=path
    )
