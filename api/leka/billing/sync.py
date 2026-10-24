"""The catalogue, in Stripe (LEKA-431): each self-service plan a product,
each price it is sold at a Stripe price, the launch offer a coupon — made
from catalogue.yaml, never typed into Stripe's dashboard.

A price is found by its lookup key, which says what it is:

    leka_core_<plan>_<interval>_<cents>     e.g. leka_core_growth_year_150360
    leka_addon_<kind>_<key>_month_<cents>   e.g. leka_addon_agent_security-review_month_2500

and each agent and bundle sold a product and a monthly price (LEKA-461),

so a price changed in the catalogue is a new Stripe price — Stripe's are
never rewritten — and what checkout charges is always what the page shows.
No price id is configured anywhere: each environment (test, live) is synced
once, then found by key.

Idempotent: what exists is left as it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from leka.billing.catalogue import INTERVALS, Catalogue, Interval, Plan, quote
from leka.billing.stripe import Stripe, StripeError


def product_id(plan: str) -> str:
    return f"leka_core_{plan}"


def lookup_key(plan: Plan, interval: Interval, offer: Catalogue, *, today: date) -> str:
    """What a plan's Stripe price is called: its plan, interval and amount —
    a month at its list price (the launch offer is a coupon on it), a year
    at its discounted total."""
    return f"leka_core_{plan.key}_{interval}_{unit_amount(plan, interval, offer, today=today)}"


def unit_amount(plan: Plan, interval: Interval, offer: Catalogue, *, today: date) -> int:
    if interval == "month":
        return int(plan.monthly_price or 0)
    return quote(plan, "year", offer, today=today).charged


def coupon_id(offer: Catalogue) -> str:
    launch = offer.launch_offer
    return f"leka_launch_{launch.percent}_{launch.months}m"


def sold(offer: Catalogue) -> list[tuple[Plan, Interval]]:
    """Every plan and interval checkout sells: the self-service plans with a
    price, monthly, and yearly when the plan is."""
    return [
        (plan, interval)
        for plan in offer.plans
        if plan.self_service and plan.monthly_price
        for interval in INTERVALS
        if interval == "month" or plan.annual
    ]


def add_on_product_id(kind: str, key: str) -> str:
    return f"leka_addon_{kind}_{key}"


def add_on_lookup_key(kind: str, key: str, cents: int) -> str:
    """What an agent's or a bundle's Stripe price is called: monthly, at its
    catalogue price — a price changed is a new Stripe price."""
    return f"leka_addon_{kind}_{key}_month_{cents}"


def sold_add_ons(offer: Catalogue) -> list[tuple[str, str, str, int]]:
    """Each agent and bundle the catalogue prices — kind, key, name, cents a
    month. Bundles not yet sellable are priced all the same: checkout still
    refuses them until every agent they name is sold."""
    sold = offer.add_ons
    if not sold.available:
        return []
    prices = sold.prices
    agents = [
        (
            "agent",
            key,
            sold.reference[agent.reference].name if agent.reference else key,
            prices[key],
        )
        for key, agent in sorted(sold.agents.items())
        if key in prices
    ]
    bundles = [("bundle", b.key, f"Bundle {b.name.en}", b.monthly_price) for b in sold.bundles]
    return agents + bundles


# The customer portal LEKA sends a subscriber to, found by this mark.
PORTAL = "leka-portal-v1"


@dataclass(frozen=True)
class Synced:
    prices: dict[str, str]  # lookup key → Stripe price id
    coupon: str
    created: list[str]
    portal: str | None = None


async def portal_configuration(stripe: Stripe) -> str | None:
    """The portal configuration LEKA made, when there is one."""
    found = await stripe.get(
        "/v1/billing_portal/configurations", [("active", "true"), ("limit", "100")]
    )
    for each in found.get("data") or []:
        if (each.get("metadata") or {}).get("leka") == PORTAL:
            return str(each["id"])
    return None


async def _product(stripe: Stripe, product: str, fields: dict[str, object]) -> bool:
    """A Stripe product, made when missing — True when it was made."""
    try:
        await stripe.get(f"/v1/products/{product}")
        return False
    except StripeError as error:
        if error.status != 404:
            raise
    await stripe.post("/v1/products", {"id": product, **fields})
    return True


async def _price_of(stripe: Stripe, key: str, fields: dict[str, object]) -> tuple[str, bool]:
    """A Stripe price by its lookup key, made when missing — its id, and
    whether it was made."""
    found = await stripe.get("/v1/prices", [("lookup_keys[]", key), ("active", "true")])
    if found.get("data"):
        return str(found["data"][0]["id"]), False
    made = await stripe.post("/v1/prices", {**fields, "lookup_key": key})
    return str(made["id"]), True


async def ensure_plan_price(
    stripe: Stripe, plan: Plan, interval: Interval, offer: Catalogue, *, today: date
) -> tuple[str, bool]:
    """A plan's price for an interval, in Stripe — made, with its product,
    when the catalogue changed since the last sync (2026-10-24: the annual
    discount went from 20 % to 30 %, and no yearly price could be bought)."""
    await _product(
        stripe,
        product_id(plan.key),
        {
            "name": f"LEKA CORE {plan.name}",
            "description": plan.value.en,
            "metadata": {"leka_plan": plan.key},
        },
    )
    return await _price_of(
        stripe,
        lookup_key(plan, interval, offer, today=today),
        {
            "product": product_id(plan.key),
            "currency": offer.currency.lower(),
            "unit_amount": unit_amount(plan, interval, offer, today=today),
            "recurring": {"interval": interval},
            "tax_behavior": "exclusive",
            "metadata": {"leka_plan": plan.key, "leka_interval": interval},
        },
    )


async def ensure_add_on_price(
    stripe: Stripe, kind: str, key: str, name: str, cents: int, offer: Catalogue
) -> tuple[str, bool]:
    """An agent's or a bundle's monthly price, in Stripe — made, with its
    product, when it was put on sale since the last sync."""
    product = add_on_product_id(kind, key)
    await _product(
        stripe,
        product,
        {"name": f"LEKA — {name}", "metadata": {"leka_add_on_kind": kind, "leka_add_on_key": key}},
    )
    return await _price_of(
        stripe,
        add_on_lookup_key(kind, key, cents),
        {
            "product": product,
            "currency": offer.currency.lower(),
            "unit_amount": cents,
            "recurring": {"interval": "month"},
            "tax_behavior": "exclusive",
            "metadata": {"leka_add_on_kind": kind, "leka_add_on_key": key},
        },
    )


async def ensure_coupon(stripe: Stripe, offer: Catalogue) -> tuple[str, bool]:
    """The launch offer's coupon, in Stripe — made when missing."""
    coupon = coupon_id(offer)
    try:
        await stripe.get(f"/v1/coupons/{coupon}")
        return coupon, False
    except StripeError as error:
        if error.status != 404:
            raise
    launch = offer.launch_offer
    await stripe.post(
        "/v1/coupons",
        {
            "id": coupon,
            "name": f"Offre de lancement -{launch.percent} % ({launch.months} mois)",
            "percent_off": launch.percent,
            "duration": "repeating",
            "duration_in_months": launch.months,
            "applies_to": {"products": sorted({product_id(p.key) for p, _ in sold(offer)})},
        },
    )
    return coupon, True


def _portal_features(plans: dict[str, list[str]]) -> dict[str, object]:
    return {
        "invoice_history": {"enabled": True},
        "payment_method_update": {"enabled": True},
        "customer_update": {
            "enabled": True,
            "allowed_updates": ["email", "address", "tax_id"],
        },
        "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
        "subscription_update": {
            "enabled": True,
            "default_allowed_updates": ["price"],
            "proration_behavior": "create_prorations",
            "products": [
                {"product": product, "prices": ids} for product, ids in sorted(plans.items())
            ],
        },
    }


async def ensure_portal(stripe: Stripe, offer: Catalogue, *, today: date) -> tuple[str, bool]:
    """The customer portal LEKA sends a subscriber to — card, invoices,
    cancellation at the period's end, a change of plan prorated — made when
    missing, and given every price the catalogue sells now: a change to a
    price it does not list is refused by Stripe (2026-10-24: monthly to
    yearly, after the annual discount changed)."""
    plans: dict[str, list[str]] = {}
    for plan, interval in sold(offer):
        price, _ = await ensure_plan_price(stripe, plan, interval, offer, today=today)
        plans.setdefault(product_id(plan.key), []).append(price)
    found = await stripe.get(
        "/v1/billing_portal/configurations", [("active", "true"), ("limit", "100")]
    )
    mine = next(
        (c for c in found.get("data") or [] if (c.get("metadata") or {}).get("leka") == PORTAL),
        None,
    )
    if mine is None:
        made = await stripe.post(
            "/v1/billing_portal/configurations",
            {
                "business_profile": {"headline": "LEKA CORE"},
                "features": _portal_features(plans),
                "metadata": {"leka": PORTAL},
            },
        )
        return str(made["id"]), True
    listed = (((mine.get("features") or {}).get("subscription_update") or {}).get("products")) or []
    allowed = {str(p.get("product")): set(p.get("prices") or []) for p in listed}
    if all(set(ids) <= allowed.get(product, set()) for product, ids in plans.items()):
        return str(mine["id"]), False
    await stripe.post(
        f"/v1/billing_portal/configurations/{mine['id']}",
        {"features": {"subscription_update": _portal_features(plans)["subscription_update"]}},
    )
    return str(mine["id"]), True


async def sync(stripe: Stripe, offer: Catalogue, *, today: date) -> Synced:
    """Every product, price and the coupon the catalogue needs, in this
    Stripe account — those missing created, the portal given every price."""
    created: list[str] = []
    prices: dict[str, str] = {}
    for plan, interval in sold(offer):
        price, made = await ensure_plan_price(stripe, plan, interval, offer, today=today)
        key = lookup_key(plan, interval, offer, today=today)
        prices[key] = price
        if made:
            created.append(key)
    for kind, key, name, cents in sold_add_ons(offer):
        price, made = await ensure_add_on_price(stripe, kind, key, name, cents, offer)
        prices[add_on_lookup_key(kind, key, cents)] = price
        if made:
            created.append(add_on_lookup_key(kind, key, cents))
    coupon, made = await ensure_coupon(stripe, offer)
    if made:
        created.append(coupon)
    portal, made = await ensure_portal(stripe, offer, today=today)
    if made:
        created.append("portal")
    return Synced(prices, coupon, created, portal)


__all__ = [
    "PORTAL",
    "Synced",
    "add_on_lookup_key",
    "add_on_product_id",
    "coupon_id",
    "ensure_add_on_price",
    "ensure_coupon",
    "ensure_plan_price",
    "ensure_portal",
    "lookup_key",
    "portal_configuration",
    "product_id",
    "sold",
    "sold_add_ons",
    "sync",
    "unit_amount",
]
