"""What it takes to carry an intention through (LEKA-439), pure: each
capability as LEKA offers it, the credits, the verdict, the least it takes.

What these protect, as the ticket lists them:
- a need Free can carry through: ready, nothing to buy;
- a need past the plan's credits: the cheapest plan that is enough — never
  the dearest by default, never a capacity pack: none is sold (LEKA-446) —
  and Enterprise by contract past Business; anything bought asked first;
- a need for an agent: in beta, usable, its future price said — never
  blocked, never sold before it is on sale, never included in a plan;
- a need several specialist agents meet: a bundle when it costs less than
  them one by one, each otherwise;
- a need nothing LEKA has meets: said impossible, never promised;
- a need a capability meets once a source is connected or a model set:
  what to do first, never offered as ready;
- a capability not ready yet: never offered as usable.
"""

from __future__ import annotations

from datetime import UTC, datetime

from leka.billing.catalogue import catalogue as sold_now
from leka.capabilities import find
from leka.capabilities.definition import Lifecycle
from leka.intentions.feasibility import Needed, offer_of, path_of
from leka.intentions.schemas import CreditsLeftRead

CREDITS = {"free": 200, "starter": 2000, "growth": 10000, "business": 40000, "enterprise": 0}
END = datetime(2026, 11, 1, tzinfo=UTC)


def month(plan: str = "free", used: float = 20, state: str = "ok") -> CreditsLeftRead:
    allowance = CREDITS[plan]
    return CreditsLeftRead(
        plan=plan,
        allowance=allowance,
        used=used,
        remaining=max(allowance - used, 0),
        state=state,
        enforced=True,
        period_end=END,
    )


def need(
    key: str,
    *,
    offer: str = "included",
    available: bool = True,
    reasons: tuple[dict[str, object], ...] = (),
    delivers: str = "finding",
    selected: bool = True,
    cost: float | None = None,
    price: int | None = None,
) -> Needed:
    return Needed(
        key=key,
        title=key,
        kind="rules",
        offer=offer,
        available=available,
        reasons=reasons,
        delivers=delivers,
        selected=selected,
        credits=cost,
        price=price,
    )


ANALYSIS = need("standing")


def test_what_free_carries_through_is_ready_nothing_to_buy() -> None:
    verdict, path = path_of([ANALYSIS], month("free"), None, sold_now(), CREDITS, expected="answer")
    assert (verdict, path) == ("ready", ())


def test_past_its_credits_the_cheapest_plan_that_is_enough_asked_first() -> None:
    # Spent on Free: Starter is enough — never the dearest.
    verdict, path = path_of(
        [ANALYSIS], month("free", 200, "exhausted"), None, sold_now(), CREDITS, expected="answer"
    )
    assert verdict == "over_quota"
    [step] = path
    assert (step.kind, step.detail["plan"], step.consent) == ("change_plan", "starter", True)
    assert step.detail["monthly_price"] == sold_now().plan("starter").monthly_price
    # A run that costs more than Starter's month: Growth, still not Business.
    agent = need("application-architecture", cost=3000, delivers="document")
    verdict, path = path_of(
        [agent], month("free", 150), 3000, sold_now(), CREDITS, expected="document"
    )
    assert verdict == "over_quota"
    assert [(s.kind, s.detail["plan"]) for s in path] == [("change_plan", "growth")]
    # Past what Business holds: Enterprise, by contract — no checkout.
    verdict, path = path_of(
        [agent], month("business", 39000), 50000, sold_now(), CREDITS, expected="document"
    )
    assert [(s.kind, s.consent) for s in path] == [("contact_sales", False)]


def test_past_the_credits_a_plan_never_a_pack() -> None:
    verdict, path = path_of(
        [need("x", cost=400)], month("free", 100), 400, sold_now(), CREDITS, expected="answer"
    )
    assert verdict == "over_quota"
    [step] = path
    assert (step.kind, step.detail["plan"], step.consent) == ("change_plan", "starter", True)


def test_every_agent_is_on_sale_free_runs_none_owned_is_never_sold_again() -> None:
    # 2026-10-14: on sale, from Starter.
    for key in ("security-review", "application-architecture"):
        found = find(key)
        assert found is not None
        assert offer_of(found, sold_now()) == "add_on"
    # On Free: the plan that runs agents first, then the agent.
    free = need(
        "security-review", offer="add_on", available=False, reasons=({"code": "plan_required"},)
    )
    verdict, path = path_of(
        [ANALYSIS, free], month("free"), None, sold_now(), CREDITS, expected="answer"
    )
    assert verdict == "prerequisites"
    assert [(s.kind, s.detail.get("plan") or s.detail.get("agent"), s.consent) for s in path] == [
        ("change_plan", "starter", True),
        ("buy_add_on", "security-review", True),
    ]
    # Owned: nothing to buy.
    mine = need("security-review", offer="add_on")
    assert path_of(
        [ANALYSIS, mine], month("growth"), None, sold_now(), CREDITS, expected="answer"
    ) == (
        "ready",
        (),
    )


def test_specialist_agents_on_sale_a_bundle_when_it_costs_less_each_otherwise() -> None:
    lacking = ({"code": "not_owned"},)
    both = [
        need("security-review", offer="add_on", available=False, reasons=lacking),
        need("infrastructure-analysis", offer="add_on", available=False, reasons=lacking),
        need("data-analysis", offer="add_on", available=False, reasons=lacking),
    ]
    verdict, path = path_of(both, month("growth"), None, sold_now(), CREDITS, expected="answer")
    assert verdict == "prerequisites"
    assert [(s.kind, s.detail.get("bundle"), s.consent) for s in path] == [
        ("buy_bundle", "security-reliability", True)
    ]
    # One alone costs less than any bundle: that one.
    verdict, path = path_of(
        [need("code-review", offer="add_on", available=False, reasons=lacking)],
        month("growth"),
        None,
        sold_now(),
        CREDITS,
        expected="answer",
    )
    assert [(s.kind, s.detail.get("agent")) for s in path] == [("buy_add_on", "code-review")]


def test_what_nothing_leka_has_makes_is_said_impossible() -> None:
    verdict, path = path_of(
        [ANALYSIS], month("growth"), None, sold_now(), CREDITS, expected="document"
    )
    assert verdict == "impossible"
    assert [s.kind for s in path] == ["rephrase"]


def test_a_source_to_connect_comes_first_never_offered_as_ready() -> None:
    architect = need(
        "application-architecture",
        available=False,
        delivers="document",
        reasons=({"code": "missing_source", "sources": ["confluence", "github"]},),
    )
    verdict, path = path_of(
        [ANALYSIS, architect], month("free"), None, sold_now(), CREDITS, expected="document"
    )
    assert verdict == "prerequisites"
    [step] = path
    assert step.kind == "connect_source"
    assert step.detail["sources"] == ["confluence", "github"]
    assert not step.consent


def test_a_capability_not_ready_yet_is_never_offered_as_usable() -> None:
    draft = find("map-service-ownership")
    assert draft is not None and draft.lifecycle is Lifecycle.DRAFT
    assert offer_of(draft, sold_now()) == "planned"
    only = need("map-service-ownership", offer="planned", available=False, delivers="document")
    verdict, _ = path_of(
        [ANALYSIS, only], month("growth"), None, sold_now(), CREDITS, expected="document"
    )
    assert verdict == "impossible"
