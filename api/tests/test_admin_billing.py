"""Subscriptions, billing and finance in LEKA ADMIN (LEKA-554): what Stripe
said, kept, read by the roles that may.

What these protect:
- Finance keeps recurring revenue, billing and collection apart: the MRR now
  and its movements, the invoices issued (VAT and prorations said apart),
  the payments taken or failed, the refunds; in euros, another currency
  counted apart, never converted; demonstration organisations left out;
  the MRR at the start and the movements set against the MRR now.
- Each list (invoices, payments, refunds, changes, Stripe's events) is read
  with its filters; an organisation's subscriptions with their history.
- Money is Finance's and the Super Admin's: Support is refused.
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.admin import AdminRole
from leka.billing import (
    BillingAccount,
    BillingInvoice,
    BillingPayment,
    BillingRefund,
    StripeEvent,
    SubscriptionChange,
)
from leka.db import session_factory, system_scope
from tests.test_admin_api import API, NOW, SUPER, World, as_, world  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

FINANCE = AdminRole.FINANCE


def _invoice(workspace: uuid.UUID, marker: str, name: str, **said: Any) -> BillingInvoice:
    values: dict[str, Any] = {
        "workspace_id": workspace,
        "id": uuid.uuid4(),
        "stripe_invoice_id": f"in_{name}_{marker}",
        "stripe_subscription_id": f"sub_{marker}",
        "number": f"LEKA-{name}",
        "status": "paid",
        "billing_reason": "subscription_cycle",
        "currency": "eur",
        "subtotal": 17900,
        "discount": 0,
        "tax": 3580,
        "total": 21480,
        "amount_paid": 21480,
        "amount_due": 21480,
        "amount_remaining": 0,
        "proration": 0,
        "issued_at": NOW - timedelta(hours=2),
        "attempts": 1,
        "lines": [{"description": "Growth", "amount": 17900, "proration": False}],
        "said_at": NOW - timedelta(hours=2),
        "said_by": f"evt_{name}_{marker}",
    }
    return BillingInvoice(**(values | said))


async def _money(world: World) -> None:
    """Alpha on Growth at 179 euros, 20 % off while its coupon lasts; the
    last hours' invoices, payments and refund; one of the demonstration's;
    an event failed, one of a customer LEKA does not know."""
    marker = world.marker
    at = NOW - timedelta(minutes=90)
    with system_scope():
        async with session_factory() as session:
            account = await session.scalar(
                select(BillingAccount).where(BillingAccount.workspace_id == world.alpha)
            )
            assert account is not None
            account.stripe_customer_id = f"cus_{marker}"
            account.stripe_subscription_id = f"sub_{marker}"
            account.recurring = {
                "amount": 17900,
                "currency": "eur",
                "interval": "month",
                "interval_count": 1,
                "discount": {
                    "percent_off": 20.0,
                    "amount_off": None,
                    "ends": (NOW + timedelta(days=60)).isoformat(),
                },
            }
            session.add_all(
                [
                    SubscriptionChange(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        event_id=f"evt_new_{marker}",
                        source="plan",
                        stripe_subscription_id=f"sub_{marker}",
                        kind="new",
                        plan_before="free",
                        plan_after="growth",
                        status_before=None,
                        status_after="active",
                        interval_after="month",
                        mrr_before=0,
                        mrr_after=14320,
                        at=at,
                    ),
                    _invoice(world.alpha, marker, "paid", proration=4000),
                    _invoice(
                        world.alpha,
                        marker,
                        "open",
                        status="open",
                        tax=None,
                        total=10000,
                        amount_paid=0,
                        amount_due=10000,
                        amount_remaining=10000,
                        issued_at=at,
                    ),
                    _invoice(
                        world.alpha,
                        marker,
                        "usd",
                        currency="usd",
                        total=5000,
                        issued_at=NOW - timedelta(hours=3),
                    ),
                    _invoice(world.demo, marker, "demo"),
                    BillingPayment(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        reference=f"in_paid_{marker}:paid",
                        stripe_invoice_id=f"in_paid_{marker}",
                        outcome="succeeded",
                        amount=21480,
                        currency="eur",
                        attempt=1,
                        at=at,
                    ),
                    BillingPayment(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        reference=f"evt_failed_{marker}",
                        stripe_invoice_id=f"in_open_{marker}",
                        outcome="failed",
                        amount=10000,
                        currency="eur",
                        attempt=1,
                        next_attempt_at=NOW + timedelta(days=3),
                        at=at,
                    ),
                    BillingRefund(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        stripe_charge_id=f"ch_{marker}",
                        stripe_invoice_id=f"in_paid_{marker}",
                        amount=5000,
                        charged=21480,
                        currency="eur",
                        reason="requested_by_customer",
                        at=at,
                        said_at=at,
                    ),
                    StripeEvent(
                        event_id=f"evt_broken_{marker}",
                        type="invoice.paid",
                        for_workspace_id=world.alpha,
                        outcome="failed",
                        detail={"error": "RuntimeError", "message": "gone", "attempts": 2},
                        received_at=at,
                    ),
                    StripeEvent(
                        event_id=f"evt_stranger_{marker}",
                        type="invoice.paid",
                        outcome="ignored",
                        detail={"why": "no_workspace"},
                        received_at=at,
                    ),
                ]
            )
            await session.commit()


async def _finance(client: AsyncClient, world: World) -> dict[str, Any]:
    response = await client.get(
        f"{API}/billing/finance", params={"period": "7d"}, headers=as_(world, FINANCE)
    )
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def _moved(before: dict[str, Any], after: dict[str, Any], *keys: str) -> float:
    """How much a figure moved, a nested one said by its keys."""
    old: Any = before
    new: Any = after
    for key in keys:
        old, new = old[key], new[key]
    return round(float(new) - float(old), 2)


async def test_finance_keeps_recurring_revenue_billing_and_collection_apart(
    client: AsyncClient, world: World
) -> None:
    before = await _finance(client, world)
    await _money(world)
    after = await _finance(client, world)

    # Recurring revenue: 179 euros, 20 % off, a month; new this period.
    assert _moved(before, after, "mrr") == 143.2
    assert _moved(before, after, "arr") == round(143.2 * 12, 2)
    assert _moved(before, after, "subscriptions") == 1
    assert (_moved(before, after, "new", "count"), _moved(before, after, "new", "eur")) == (
        1,
        143.2,
    )
    growth = next(p for p in after["by_plan"] if p["plan"] == "growth")
    growth_before = next((p for p in before["by_plan"] if p["plan"] == "growth"), None)
    assert round(growth["mrr"] - (growth_before["mrr"] if growth_before else 0), 2) == 143.2
    assert round(sum(p["mrr"] for p in after["by_plan"]), 2) == after["mrr"]
    # The MRR at the start and the movements, set against the MRR now.
    if after["mrr_explained"] is not None:
        assert after["mrr_gap"] == round(after["mrr"] - after["mrr_explained"], 2)

    # Billing: the paid and the open invoice, VAT and prorations said apart;
    # the one in dollars counted apart; the demonstration's left out.
    assert _moved(before, after, "invoices") == 2
    assert _moved(before, after, "invoiced") == 314.8
    assert _moved(before, after, "invoiced_tax") == 35.8
    assert _moved(before, after, "prorations") == 40.0
    assert (_moved(before, after, "open_invoices"), _moved(before, after, "open_amount")) == (
        1,
        100.0,
    )
    assert _moved(before, after, "other_currencies") == 1

    # Collection: taken, failed, given back.
    assert (_moved(before, after, "payments_succeeded"), _moved(before, after, "collected")) == (
        1,
        214.8,
    )
    assert (_moved(before, after, "payments_failed"), _moved(before, after, "failed_amount")) == (
        1,
        100.0,
    )
    assert (_moved(before, after, "refunds"), _moved(before, after, "refunded")) == (1, 50.0)
    assert _moved(before, after, "net_collected") == 164.8

    # Stripe's events: one failed, one of a customer LEKA does not know.
    assert _moved(before, after, "failed_events") == 1
    assert _moved(before, after, "unlinked_events") == 1
    assert after["events"]["failed"] >= 1 and after["last_event_at"] is not None

    custom = await client.get(
        f"{API}/billing/finance", params={"period": "custom"}, headers=as_(world, FINANCE)
    )
    assert custom.status_code == 400


async def test_invoices_payments_refunds_and_changes_are_read_with_their_filters(
    client: AsyncClient, world: World
) -> None:
    await _money(world)
    alpha = {"organisation_id": str(world.alpha)}

    invoices = await client.get(f"{API}/billing/invoices", params=alpha, headers=as_(world, SUPER))
    assert invoices.status_code == 200, invoices.text
    rows = invoices.json()["data"]
    # The latest issued first.
    assert [r["number"] for r in rows] == ["LEKA-open", "LEKA-paid", "LEKA-usd"]
    paid = rows[1]
    assert (paid["total"], paid["tax"], paid["proration"], paid["currency"]) == (
        214.8,
        35.8,
        40.0,
        "eur",
    )
    assert paid["organisation"] == {"id": str(world.alpha), "name": f"Alpha {world.marker}"}
    # Each line in euros, like its invoice.
    assert paid["lines"] == [
        {"description": "Growth", "amount": 179.0, "proration": False, "start": None, "end": None}
    ]
    opened = await client.get(
        f"{API}/billing/invoices",
        params={"organisation": f"alpha-{world.marker}", "status": "open"},
        headers=as_(world, FINANCE),
    )
    assert [(r["number"], r["amount_remaining"]) for r in opened.json()["data"]] == [
        ("LEKA-open", 100.0)
    ]

    failed = await client.get(
        f"{API}/billing/payments",
        params=alpha | {"outcome": "failed"},
        headers=as_(world, FINANCE),
    )
    [payment] = failed.json()["data"]
    assert (payment["amount"], payment["attempt"], payment["invoice"]) == (
        100.0,
        1,
        f"in_open_{world.marker}",
    )
    assert payment["next_attempt_at"] is not None

    refunds = await client.get(f"{API}/billing/refunds", params=alpha, headers=as_(world, FINANCE))
    [refund] = refunds.json()["data"]
    assert (refund["amount"], refund["charged"], refund["reason"]) == (
        50.0,
        214.8,
        "requested_by_customer",
    )

    changes = await client.get(
        f"{API}/billing/changes", params=alpha | {"kind": "new"}, headers=as_(world, FINANCE)
    )
    [change] = changes.json()["data"]
    assert (change["plan_before"], change["plan_after"], change["mrr_after_eur"]) == (
        "free",
        "growth",
        143.2,
    )
    none = await client.get(
        f"{API}/billing/changes", params=alpha | {"kind": "churn"}, headers=as_(world, FINANCE)
    )
    assert none.json()["data"] == []
    unknown_kind = await client.get(
        f"{API}/billing/changes", params={"kind": "refund"}, headers=as_(world, FINANCE)
    )
    assert unknown_kind.status_code == 422

    unlinked = await client.get(
        f"{API}/billing/events",
        params={"linked": "false", "limit": 200},
        headers=as_(world, FINANCE),
    )
    assert f"evt_stranger_{world.marker}" in {e["event_id"] for e in unlinked.json()["data"]}
    assert all(e["organisation"] is None for e in unlinked.json()["data"])
    broken = await client.get(
        f"{API}/billing/events", params=alpha | {"outcome": "failed"}, headers=as_(world, FINANCE)
    )
    [event] = broken.json()["data"]
    assert event["detail"] == {"error": "RuntimeError", "message": "gone", "attempts": 2}


async def test_an_organisation_s_subscriptions_with_their_history(
    client: AsyncClient, world: World
) -> None:
    await _money(world)
    listed = await client.get(
        f"{API}/subscriptions",
        params={"organisation": f"alpha-{world.marker}"},
        headers=as_(world, FINANCE),
    )
    [row] = listed.json()["data"]
    assert (row["plan"], row["price_eur"], row["mrr_eur"], row["add_ons"]) == (
        "growth",
        179.0,
        143.2,
        0,
    )
    assert row["discount"]["percent_off"] == 20.0 and row["discount"]["ends"] is not None
    assert row["stripe_subscription_id"] == f"sub_{world.marker}"
    assert row["since"] is not None

    detail = await client.get(f"{API}/subscriptions/{world.alpha}", headers=as_(world, FINANCE))
    assert detail.status_code == 200, detail.text
    said = detail.json()
    assert said["subscription"]["plan"] == "growth"
    assert [c["kind"] for c in said["changes"]] == ["new"]
    assert [i["number"] for i in said["invoices"]] == ["LEKA-open", "LEKA-paid", "LEKA-usd"]
    assert sorted(p["outcome"] for p in said["payments"]) == ["failed", "succeeded"]
    assert [r["amount"] for r in said["refunds"]] == [50.0]
    assert said["add_ons"] == []

    # An organisation never subscribed: on Free, nothing to show.
    demo = (await client.get(f"{API}/subscriptions/{world.demo}", headers=as_(world, SUPER))).json()
    assert (demo["subscription"]["plan"], demo["subscription"]["mrr_eur"]) == ("free", 0.0)
    assert (demo["changes"], demo["payments"]) == ([], [])
    nobody = await client.get(f"{API}/subscriptions/{uuid.uuid4()}", headers=as_(world, SUPER))
    assert nobody.status_code == 404


async def test_money_is_refused_to_support(client: AsyncClient, world: World) -> None:
    for path in (
        "/billing/finance",
        "/billing/invoices",
        "/billing/payments",
        "/billing/refunds",
        "/billing/changes",
        f"/subscriptions/{world.alpha}",
    ):
        refused = await client.get(f"{API}{path}", headers=as_(world, AdminRole.SUPPORT))
        assert refused.status_code == 403, path
