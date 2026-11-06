"""What a subscription brings in each month (LEKA-548), as Stripe last said it.

A subscription's recurring price is kept beside its state: the plan's on
`billing_accounts.recurring`, an add-on's on `agent_entitlements.recurring`.
It is read from the subscription Stripe sends with each of its events, or
once from Stripe for a subscription already running before LEKA kept it
(`python -m leka.billing.cli amounts`):

    {"amount": 5900, "currency": "eur", "interval": "month", "interval_count": 1,
     "discount": {"percent_off": 20.0, "amount_off": null, "ends": "2027-11-06T…"}}

`amount` is the list price of every item (unit price times quantity), in cents,
for one interval, excluding VAT like the catalogue's prices. `discount` is
the coupon on the subscription and when it ends (null: as long as the
subscription lasts). `monthly()` says what that brings in a month at a given
moment: a yearly price counts as twelve months, the coupon is taken off while
it lasts, and a tax is never revenue.

What Stripe cannot say as one fixed amount (a price by tiers or by usage,
items in two currencies or two intervals) is kept as unknown, never 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

# One interval, in months.
MONTHS = {"day": 12 / 365, "week": 12 / 52, "month": 1.0, "year": 12.0}


def _discount(subscription: Mapping[str, Any]) -> dict[str, Any] | None:
    found = subscription.get("discount")
    if not isinstance(found, Mapping):
        # Newer API versions list them; only an expanded one says its coupon.
        found = next(
            (d for d in subscription.get("discounts") or [] if isinstance(d, Mapping)), None
        )
    if not found:
        return None
    coupon = found.get("coupon") or {}
    percent, off = coupon.get("percent_off"), coupon.get("amount_off")
    if percent is None and off is None:
        return None
    end = found.get("end")
    return {
        "percent_off": float(percent) if percent is not None else None,
        "amount_off": int(off) if off is not None else None,
        "ends": datetime.fromtimestamp(int(end), UTC).isoformat() if end else None,
    }


def recurring_of(subscription: Mapping[str, Any]) -> dict[str, Any] | None:
    """A Stripe subscription's recurring price, as kept; None: not one fixed amount."""
    items = (subscription.get("items") or {}).get("data") or []
    amount = 0
    currency: str | None = None
    interval: tuple[str, int] | None = None
    for item in items:
        price = item.get("price") or {}
        unit = price.get("unit_amount")
        recurring = price.get("recurring") or {}
        said = (str(recurring.get("interval") or ""), int(recurring.get("interval_count") or 1))
        if unit is None or said[0] not in MONTHS or said[1] < 1:
            return None
        if interval is None:
            interval, currency = said, str(price.get("currency") or "").lower() or None
        elif said != interval or str(price.get("currency") or "").lower() != currency:
            return None
        amount += int(unit) * int(item.get("quantity") or 1)
    if interval is None or currency is None:
        return None
    return {
        "amount": amount,
        "currency": currency,
        "interval": interval[0],
        "interval_count": interval[1],
        "discount": _discount(subscription),
    }


def monthly(recurring: Mapping[str, Any] | None, at: datetime) -> float | None:
    """What it brings in a month at `at`, in cents; None: not known."""
    if not recurring:
        return None
    try:
        amount = float(recurring["amount"])
        interval = str(recurring["interval"])
        count = int(recurring.get("interval_count") or 1)
    except (KeyError, TypeError, ValueError):
        return None
    if interval not in MONTHS or count < 1:
        return None
    discount = recurring.get("discount") or None
    if discount:
        ends = discount.get("ends")
        if ends is None or datetime.fromisoformat(str(ends)) > at:
            if discount.get("percent_off") is not None:
                amount *= 1 - float(discount["percent_off"]) / 100
            elif discount.get("amount_off") is not None:
                amount = max(0.0, amount - float(discount["amount_off"]))
    return amount / (MONTHS[interval] * count)


__all__ = ["MONTHS", "monthly", "recurring_of"]
