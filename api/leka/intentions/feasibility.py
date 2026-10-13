"""What it takes to carry an intention through (LEKA-439): the capabilities it
needs, whether this workspace may use each — its plan, its credits, what is
connected, who asks — and, when it cannot, the least it takes to.

    the capabilities   what the router sends it to (LEKA-398) — LEKA's own
                       analysis always — for this person, as the catalogue
                       stands; each said
                         included     LEKA's own, and the core agents every
                                      plan has (billing/catalogue.yaml)
                         beta         a specialist agent while it is not on
                                      sale: usable, its future price said
                                      (decided 2026-10-13)
                         add_on       a specialist agent on sale: bought
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
                       allow; a capacity pack; an add-on, or a bundle when it
                       costs less than its agents one by one; the cheapest
                       plan that is enough — never the dearest by default;
                       Enterprise by contract. Anything bought is consented
                       to first: nothing here buys.

It reads; it never changes anything.
"""

from __future__ import annotations

import statistics
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing.catalogue import Catalogue
from leka.billing.catalogue import catalogue as billing_catalogue
from leka.capabilities import AgentRun, CatalogueService, ModelCall, find
from leka.capabilities.definition import Availability, Definition, Kind, Lifecycle
from leka.capabilities.router import Routing, route
from leka.governance import credits_of
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

    kind: str  # connect_source, ask_admin, configure_model, enable, buy_pack,
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


def offer_of(definition: Definition, sold: Catalogue) -> str:
    """How LEKA offers it: included, beta, add_on or planned."""
    if definition.lifecycle in (Lifecycle.DRAFT, Lifecycle.REVIEW):
        return "planned"
    if definition.kind is Kind.WORKFLOW:
        offers = {
            offer_of(step, sold)
            for step in _steps(definition)
            if step is not None and step.kind is not Kind.WORKFLOW
        }
        for worst in ("planned", "add_on", "beta"):
            if worst in offers:
                return worst
        return "included"
    if definition.kind is not Kind.AGENT:
        return "included"
    if definition.key in {agent.key for agent in sold.core_agents}:
        return "included"
    if definition.key in sold.add_ons.agents:
        return "add_on" if sold.add_ons.available else "beta"
    return "included"


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
        offer = offer_of(definition, sold)
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
    add_ons = sorted({n.key for n in used if n.offer == "add_on"})
    if add_ons:
        steps += _bought(add_ons, sold)
    short = month.state == "exhausted" or (estimate is not None and month.remaining < estimate)
    if short:
        missing = (estimate or 0) - month.remaining
        pack = next(
            (p for p in sorted(sold.capacity.packs, key=lambda p: p.price) if p.credits >= missing),
            None,
        )
        if pack is not None and missing > 0:
            steps.append(
                Step(
                    "buy_pack",
                    {"pack": pack.key, "credits": pack.credits, "price": pack.price},
                    consent=True,
                )
            )
        else:
            # A month that is enough: what it used and what it needs.
            need = month.used + (estimate or 1)
            plan = _plan_enough(sold, plan_credits, need)
            current = PLANS.index(month.plan)
            if plan is not None and PLANS.index(plan) > current:
                price = sold.plan(plan).monthly_price
                steps.append(
                    Step("change_plan", {"plan": plan, "monthly_price": price}, consent=True)
                )
            else:
                steps.append(Step("contact_sales", {"plan": "enterprise"}))
        return "over_quota", tuple(steps)
    if steps:
        return "prerequisites", tuple(steps)
    return "ready", ()


def _bought(add_ons: Sequence[str], sold: Catalogue) -> list[Step]:
    """Specialist agents on sale: a bundle when it costs less than them one
    by one, else each."""
    wanted = set(add_ons)
    alone = sum(sold.add_ons.prices.get(key, 0) for key in add_ons)
    priced = all(key in sold.add_ons.prices for key in add_ons)
    bundles = sorted(
        (b for b in sold.add_ons.bundles if wanted <= set(b.agents)),
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
                },
                consent=True,
            )
        ]
    return [
        Step(
            "buy_add_on",
            {"agent": key, "monthly_price": sold.add_ons.prices.get(key)},
            consent=True,
        )
        for key in add_ons
    ]


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
    needed = needed_of(routing, entries, sold, costs)
    # Metering reads intentions: read here, not at import.
    from leka.metering.credits import credits_now

    month = CreditsLeftRead.model_validate(
        (await credits_now(session, workspace_id, now=now)).model_dump()
    )
    spends = [n.credits for n in needed if n.selected and n.credits is not None]
    estimate = round(sum(spends), 2) if spends else None
    expected = next((s.value for s in brief.slots if s.slot == "expected"), "answer") or "answer"
    allowances = plan_credits or {plan: credits_for(plan) for plan in PLANS}
    verdict, path = path_of(needed, month, estimate, sold, allowances, expected=expected)
    return Feasibility(
        verdict=verdict, needed=tuple(needed), credits=month, estimate=estimate, path=path
    )
