"""The catalogue, in Stripe (LEKA-431): each self-service plan a product,
each price it is sold at a Stripe price, the launch offer a coupon — made
from catalogue.yaml, never typed into Stripe's dashboard.

A price is found by its lookup key, which says what it is:

    leka_core_<plan>_<interval>_<cents>     e.g. leka_core_growth_year_171840

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


async def sync(stripe: Stripe, offer: Catalogue, *, today: date) -> Synced:
    """Every product, price and the coupon the catalogue needs, in this
    Stripe account — those missing created."""
    created: list[str] = []
    prices: dict[str, str] = {}
    for plan in {p for p, _ in sold(offer)}:
        try:
            await stripe.get(f"/v1/products/{product_id(plan.key)}")
        except StripeError as error:
            if error.status != 404:
                raise
            await stripe.post(
                "/v1/products",
                {
                    "id": product_id(plan.key),
                    "name": f"LEKA CORE {plan.name}",
                    "description": plan.value.en,
                    "metadata": {"leka_plan": plan.key},
                },
            )
            created.append(product_id(plan.key))
    for plan, interval in sold(offer):
        key = lookup_key(plan, interval, offer, today=today)
        found = await stripe.get("/v1/prices", [("lookup_keys[]", key), ("active", "true")])
        if found.get("data"):
            prices[key] = str(found["data"][0]["id"])
            continue
        made = await stripe.post(
            "/v1/prices",
            {
                "product": product_id(plan.key),
                "currency": offer.currency.lower(),
                "unit_amount": unit_amount(plan, interval, offer, today=today),
                "recurring": {"interval": interval},
                "lookup_key": key,
                "tax_behavior": "exclusive",
                "metadata": {"leka_plan": plan.key, "leka_interval": interval},
            },
        )
        prices[key] = str(made["id"])
        created.append(key)
    coupon = coupon_id(offer)
    try:
        await stripe.get(f"/v1/coupons/{coupon}")
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
        created.append(coupon)
    # The customer portal: card, invoices, cancellation at the period's end,
    # a change of plan prorated — the documented policy (docs/pricing.md).
    portal = await portal_configuration(stripe)
    if portal is None:
        plans: dict[str, list[str]] = {}
        for plan, interval in sold(offer):
            plans.setdefault(product_id(plan.key), []).append(
                prices[lookup_key(plan, interval, offer, today=today)]
            )
        made = await stripe.post(
            "/v1/billing_portal/configurations",
            {
                "business_profile": {"headline": "LEKA CORE"},
                "features": {
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
                            {"product": product, "prices": ids}
                            for product, ids in sorted(plans.items())
                        ],
                    },
                },
                "metadata": {"leka": PORTAL},
            },
        )
        portal = str(made["id"])
        created.append("portal")
    return Synced(prices, coupon, created, portal)


__all__ = [
    "PORTAL",
    "Synced",
    "coupon_id",
    "lookup_key",
    "portal_configuration",
    "product_id",
    "sold",
    "sync",
    "unit_amount",
]
