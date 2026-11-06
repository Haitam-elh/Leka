"""What a subscription brings in each month (LEKA-548), read from Stripe's own
subscription: the list price of its items, a coupon off while it lasts, a
year spread over twelve months — and what is not one fixed amount said as
unknown, never 0. What an invoice or a refund moved, kept apart."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from leka.billing import monthly, recurring_of
from leka.billing.subscriptions import _amounts

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def _subscription(*items: dict[str, Any], discount: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": "sub_1", "items": {"data": list(items)}, "discount": discount}


def _item(
    unit: int | None, *, interval: str = "month", quantity: int = 1, currency: str = "eur"
) -> dict[str, Any]:
    return {
        "quantity": quantity,
        "price": {"unit_amount": unit, "currency": currency, "recurring": {"interval": interval}},
    }


def test_the_launch_coupon_comes_off_a_monthly_price_while_it_lasts() -> None:
    ends = NOW + timedelta(days=300)
    kept = recurring_of(
        _subscription(
            _item(5900),
            discount={
                "coupon": {"percent_off": 20, "amount_off": None},
                "end": int(ends.timestamp()),
            },
        )
    )
    assert kept == {
        "amount": 5900,
        "currency": "eur",
        "interval": "month",
        "interval_count": 1,
        "discount": {"percent_off": 20.0, "amount_off": None, "ends": ends.isoformat()},
    }
    assert monthly(kept, NOW) == 4720
    # Once the coupon has ended: the whole price.
    assert monthly(kept, ends + timedelta(days=1)) == 5900


def test_a_yearly_price_is_twelve_months_and_items_add_up() -> None:
    yearly = recurring_of(_subscription(_item(120_000, interval="year")))
    assert monthly(yearly, NOW) == 10_000
    two_seats = recurring_of(_subscription(_item(1500, quantity=2), _item(900)))
    assert two_seats is not None and two_seats["amount"] == 3900
    off = recurring_of(_subscription(_item(5900), discount={"coupon": {"amount_off": 900}}))
    assert monthly(off, NOW) == 5000


def test_what_is_not_one_fixed_amount_is_unknown_never_zero() -> None:
    # A price by tiers or by usage has no unit amount.
    assert recurring_of(_subscription(_item(None))) is None
    # Two currencies, two intervals: not one amount.
    assert recurring_of(_subscription(_item(5900), _item(900, currency="usd"))) is None
    assert recurring_of(_subscription(_item(5900), _item(900, interval="year"))) is None
    assert recurring_of(_subscription()) is None
    assert monthly(None, NOW) is None
    assert monthly({"amount": 5900}, NOW) is None
    # A free price is a true 0.
    assert monthly(recurring_of(_subscription(_item(0))), NOW) == 0


def test_an_invoice_says_what_was_paid_and_its_tax_a_refund_what_went_back() -> None:
    assert _amounts(
        "invoice.paid", {"amount_paid": 5664, "tax": 944, "currency": "EUR", "amount_due": 5664}
    ) == {"amount": 5664, "currency": "eur", "tax": 944}
    assert _amounts("invoice.payment_failed", {"amount_due": 5664, "currency": "eur"}) == {
        "amount": 5664,
        "currency": "eur",
    }
    assert _amounts("charge.refunded", {"amount_refunded": 2000, "currency": "eur"}) == {
        "amount": 2000,
        "currency": "eur",
    }
    # Not said: nothing kept, rather than a 0.
    assert _amounts("invoice.paid", {"currency": "eur"}) == {}
    assert _amounts("customer.subscription.updated", {"amount_paid": 1}) == {}
