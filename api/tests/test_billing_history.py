"""What Stripe said of money, kept (LEKA-554), on a Stripe whose API is faked,
its webhooks signed as Stripe signs them.

What these protect:
- Each change of a subscription is kept once, its kind said from what it
  brings in a month (else its plan): new, up, down, its renewal stopped,
  ended; a delivery again writes nothing more.
- Invoices, payments and refunds are kept as Stripe last said them: an
  older word never undoes a newer one, a payment is written once, a charge
  refunded twice is one refund of its whole amount. No card data is kept.
- A delivery that fails is kept failed, its error and attempts said, and
  applied when Stripe delivers it again; then never twice.
- Read again from Stripe's API: the invoices and refunds the webhooks
  missed, every page; each subscription set beside Stripe's, every
  difference said, the MRR both ways.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.billing import (
    BillingAccount,
    BillingInvoice,
    BillingPayment,
    BillingRefund,
    StripeEvent,
    SubscriptionChange,
    SubscriptionState,
    kind_of,
)
from leka.billing import subscriptions as billing
from leka.billing.reconcile import read_history, reconcile
from leka.billing.stripe import sign
from leka.db import session_factory, system_scope
from tests.conftest import FakeIdentity
from tests.test_billing_stripe import (  # noqa: F401 — a fixture
    API,
    SECRET,
    FakeStripe,
    _deliver,
    _event,
    _priced,
    _synced,
    stripe,
    subscription,
)
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

# ── pure ────────────────────────────────────────────────────────────────────


def _state(
    plan: str | None,
    status: str | None,
    mrr: int | None,
    *,
    interval: str = "month",
    ending: bool = False,
) -> SubscriptionState:
    return SubscriptionState(
        plan=plan, status=status, interval=interval, cancel_at_period_end=ending, mrr=mrr
    )


def test_what_a_change_was_said_from_what_it_brings_in_else_its_plan() -> None:
    growth = _state("growth", "active", 17900)
    assert kind_of(_state(None, None, None), _state("growth", "trialing", 17900)) == "trial"
    assert kind_of(_state("growth", "trialing", 17900), growth) == "new"
    assert kind_of(_state("free", None, None), growth) == "new"
    assert kind_of(_state("growth", "canceled", 0), growth) == "reactivation"
    assert kind_of(growth, _state("business", "active", 39900)) == "upgrade"
    # A coupon on a dearer plan: what it brings in decides, not its name.
    assert kind_of(growth, _state("business", "active", 9900)) == "downgrade"
    # Its price not known: its plan decides.
    assert kind_of(_state("business", "active", None), _state("starter", "past_due", None)) == (
        "downgrade"
    )
    assert kind_of(growth, _state("growth", "active", 17900, interval="year")) == "interval"
    assert kind_of(growth, _state("growth", "active", 17900, ending=True)) == "renewal_off"
    assert kind_of(_state("growth", "active", 17900, ending=True), growth) == "renewal_on"
    assert kind_of(_state("growth", "past_due", 17900), _state("growth", "unpaid", 0)) == "churn"
    # Retried by Stripe, still earning: nothing that counts.
    assert kind_of(growth, _state("growth", "past_due", 17900)) is None
    assert kind_of(_state(None, "incomplete", None), _state(None, "incomplete_expired", 0)) is None


# ── a subscription's changes ────────────────────────────────────────────────


async def _subscribed(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], stripe: FakeStripe
) -> uuid.UUID:
    """Acme on Growth at 179 euros a month, from a verified checkout."""
    workspace = acme["acme"]
    await _synced(stripe)
    _as(identity, acme, "admin")
    await client.post(f"{API}/checkout", json={"plan": "growth", "interval": "month"})
    stripe.subscriptions["sub_1"] = _priced(subscription("growth", "active"), 17900)
    completed = _event(
        "checkout.session.completed",
        {
            "id": "cs_1",
            "mode": "subscription",
            "subscription": "sub_1",
            "customer": "cus_1",
            "client_reference_id": str(workspace),
        },
        created=1_800_000_100,
    )
    assert (await _deliver(client, completed)).json() == {"received": "plan:growth"}
    return workspace


async def _rows(table: type[Any], workspace: uuid.UUID, order: Any) -> list[Any]:
    with system_scope():
        async with session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(table).where(table.workspace_id == workspace).order_by(order)
                    )
                ).all()
            )


async def _changes(workspace: uuid.UUID) -> list[tuple[Any, ...]]:
    return [
        (c.kind, c.plan_before, c.plan_after, c.mrr_before, c.mrr_after)
        for c in await _rows(SubscriptionChange, workspace, SubscriptionChange.at)
    ]


@pytest.mark.integration
async def test_each_change_of_a_subscription_is_kept_once_with_what_it_moved(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    workspace = await _subscribed(client, identity, acme, stripe)
    assert await _changes(workspace) == [("new", "free", "growth", 0, 17900)]

    upgraded = _event(
        "customer.subscription.updated",
        _priced(subscription("business", "active"), 39900),
        created=1_800_000_200,
    )
    assert (await _deliver(client, upgraded)).json() == {"received": "plan:business"}
    # Delivered again: nothing more.
    assert (await _deliver(client, upgraded)).json() == {"received": "duplicate"}
    ending = _priced(subscription("business", "active"), 39900)
    ending["cancel_at_period_end"] = True
    stopped = _event("customer.subscription.updated", ending, created=1_800_000_300)
    assert (await _deliver(client, stopped)).json() == {"received": "plan:business"}
    # Retried by Stripe, still earning: no change that counts.
    retried = _priced(subscription("business", "past_due"), 39900)
    retried["cancel_at_period_end"] = True
    await _deliver(client, _event("customer.subscription.updated", retried, created=1_800_000_350))
    deleted = _event(
        "customer.subscription.deleted",
        _priced(subscription("business", "canceled"), 39900),
        created=1_800_000_400,
    )
    assert (await _deliver(client, deleted)).json() == {"received": "plan:free"}

    assert await _changes(workspace) == [
        ("new", "free", "growth", 0, 17900),
        ("upgrade", "growth", "business", 17900, 39900),
        ("renewal_off", "business", "business", 39900, 39900),
        ("churn", "business", "free", 39900, 0),
    ]
    changes = await _rows(SubscriptionChange, workspace, SubscriptionChange.at)
    assert {c.source for c in changes} == {"plan"}
    assert {c.stripe_subscription_id for c in changes} == {"sub_1"}
    assert changes[1].at == datetime.fromtimestamp(1_800_000_200, UTC)


# ── invoices, payments, refunds ─────────────────────────────────────────────


def _invoice(invoice_id: str, status: str, **said: Any) -> dict[str, Any]:
    return {
        "id": invoice_id,
        "object": "invoice",
        "customer": "cus_1",
        "subscription": "sub_1",
        "number": "LEKA-0042",
        "status": status,
        "billing_reason": "subscription_update",
        "currency": "eur",
        "subtotal": 17900,
        "total_discount_amounts": [{"amount": 0}],
        "tax": 3580,
        "total": 21480,
        "amount_due": 21480,
        "amount_paid": 0,
        "amount_remaining": 21480,
        "created": 1_800_000_500,
        "period_start": 1_800_000_000,
        "period_end": 1_802_592_000,
        "attempt_count": 0,
        "hosted_invoice_url": "https://invoice.stripe.test/i_1",
        "lines": {
            "data": [
                {"description": "Growth", "amount": 17900, "period": {"start": 1_800_000_000}},
                {"description": "Remaining time on Business", "amount": 12000, "proration": True},
                {"description": "Unused time on Growth", "amount": -8000, "proration": True},
            ]
        },
        # What Stripe also says of the card, never kept.
        "payment_settings": {"payment_method_types": ["card"]},
        "charge": "ch_card_1",
        "default_payment_method": {
            "card": {"brand": "visa", "last4": "4242", "fingerprint": "fp_never_kept"}
        },
    } | said


def _charge(charge_id: str, invoice_id: str, refunded: int, *, at: int) -> dict[str, Any]:
    return {
        "id": charge_id,
        "object": "charge",
        "customer": "cus_1",
        "invoice": invoice_id,
        "amount": 21480,
        "amount_refunded": refunded,
        "currency": "eur",
        "refunded": refunded == 21480,
        "payment_method_details": {
            "card": {"brand": "visa", "last4": "4242", "fingerprint": "fp_never_kept"}
        },
        "refunds": {"data": [{"id": f"re_{at}", "reason": "requested_by_customer", "created": at}]},
    }


@pytest.mark.integration
async def test_invoices_payments_and_refunds_are_kept_as_stripe_last_said_them(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    workspace = await _subscribed(client, identity, acme, stripe)
    invoice = f"in_{uuid.uuid4().hex[:10]}"
    charge = f"ch_{uuid.uuid4().hex[:10]}"

    # Finalized: no plan changes, the invoice is kept all the same.
    finalized = _event("invoice.finalized", _invoice(invoice, "open"), created=1_800_000_500)
    assert (await _deliver(client, finalized)).json() == {"received": "kept"}
    failed = _event(
        "invoice.payment_failed",
        _invoice(invoice, "open", attempt_count=1, next_payment_attempt=1_800_090_000),
        created=1_800_000_600,
    )
    assert (await _deliver(client, failed)).json() == {"received": "payment_failed"}
    assert (await _deliver(client, failed)).json() == {"received": "duplicate"}
    paid = _event(
        "invoice.paid",
        _invoice(
            invoice,
            "paid",
            amount_paid=21480,
            amount_remaining=0,
            attempt_count=2,
            status_transitions={"paid_at": 1_800_090_100},
        ),
        created=1_800_090_100,
    )
    assert (await _deliver(client, paid)).json() == {"received": "paid"}
    # An older word, delivered late, never undoes it.
    late = _event("invoice.updated", _invoice(invoice, "open"), created=1_800_000_550)
    await _deliver(client, late)

    [kept] = await _rows(BillingInvoice, workspace, BillingInvoice.issued_at)
    assert (kept.stripe_invoice_id, kept.status, kept.number) == (invoice, "paid", "LEKA-0042")
    assert (kept.subtotal, kept.discount, kept.tax, kept.total) == (17900, 0, 3580, 21480)
    assert (kept.amount_paid, kept.amount_remaining, kept.attempts) == (21480, 0, 2)
    assert kept.proration == 4000  # 120 on Business, less 80 unused on Growth.
    assert [line["proration"] for line in kept.lines] == [False, True, True]
    assert kept.paid_at == datetime.fromtimestamp(1_800_090_100, UTC)
    assert kept.said_by == paid["id"]

    payments = await _rows(BillingPayment, workspace, BillingPayment.at)
    assert [(p.outcome, p.amount, p.attempt) for p in payments] == [
        ("failed", 21480, 1),
        ("succeeded", 21480, 2),
    ]
    assert payments[0].next_attempt_at == datetime.fromtimestamp(1_800_090_000, UTC)
    assert payments[1].reference == f"{invoice}:paid"

    # Refunded in two goes: one refund, of what the charge gave back in all.
    for refunded, at in ((5000, 1_800_100_000), (21480, 1_800_200_000)):
        said = _event("charge.refunded", _charge(charge, invoice, refunded, at=at), created=at)
        assert (await _deliver(client, said)).json() == {"received": "refund_kept"}
    [refund] = await _rows(BillingRefund, workspace, BillingRefund.at)
    assert (refund.stripe_charge_id, refund.amount, refund.charged) == (charge, 21480, 21480)
    assert (refund.reason, refund.at) == (
        "requested_by_customer",
        datetime.fromtimestamp(1_800_200_000, UTC),
    )

    # No card data, anywhere it was kept.
    with system_scope():
        async with session_factory() as session:
            details = (
                await session.scalars(
                    select(StripeEvent.detail).where(StripeEvent.for_workspace_id == workspace)
                )
            ).all()
    written = json.dumps(
        [
            [str(getattr(row, c.key)) for c in type(row).__table__.columns]
            for row in [kept, *payments, refund]
        ]
        + list(details)
    )
    assert not [said for said in ("fp_never_kept", "visa", "last4") if said in written]


@pytest.mark.integration
async def test_a_delivery_that_fails_is_kept_failed_then_applied_once_delivered_again(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = await _subscribed(client, identity, acme, stripe)
    invoice = f"in_{uuid.uuid4().hex[:10]}"
    keep = billing._keep_money
    broken = {"times": 2}

    async def failing(*args: Any, **kwargs: Any) -> bool:
        if broken["times"]:
            broken["times"] -= 1
            raise RuntimeError("the database went away")
        return await keep(*args, **kwargs)

    monkeypatch.setattr(billing, "_keep_money", failing)
    event = _event("invoice.finalized", _invoice(invoice, "open"), created=1_800_000_500)
    body = json.dumps(event).encode()

    async def delivered() -> str:
        return await billing.receive(
            body,
            sign(body, SECRET, at=int(time.time())),
            now=datetime.now(UTC),
            client=stripe.client(),
        )

    async def kept_event() -> StripeEvent:
        with system_scope():
            async with session_factory() as session:
                found = await session.scalar(
                    select(StripeEvent).where(StripeEvent.event_id == event["id"])
                )
                assert found is not None
                return found

    for attempt in (1, 2):
        with pytest.raises(RuntimeError):
            await delivered()
        failed = await kept_event()
        assert (failed.outcome, failed.for_workspace_id) == ("failed", workspace)
        assert failed.detail == {
            "error": "RuntimeError",
            "message": "the database went away",
            "attempts": attempt,
        }
        # Rolled back: nothing of it kept.
        assert await _rows(BillingInvoice, workspace, BillingInvoice.issued_at) == []

    assert await delivered() == "kept"
    applied = await kept_event()
    assert applied.outcome == "applied"
    assert applied.detail["attempts"] == 3
    assert len(await _rows(BillingInvoice, workspace, BillingInvoice.issued_at)) == 1
    # Applied once: never again.
    assert await delivered() == "duplicate"


@pytest.mark.integration
async def test_an_event_of_a_customer_leka_does_not_know_is_kept_unlinked(
    client: AsyncClient, stripe: FakeStripe
) -> None:
    stranger = _event(
        "invoice.paid",
        _invoice(f"in_{uuid.uuid4().hex[:10]}", "paid", customer="cus_nobody"),
        created=5,
    )
    assert (await _deliver(client, stranger)).json() == {"received": "ignored"}
    with system_scope():
        async with session_factory() as session:
            kept = await session.scalar(
                select(StripeEvent).where(StripeEvent.event_id == stranger["id"])
            )
            invoices = await session.scalar(
                select(BillingInvoice).where(
                    BillingInvoice.stripe_invoice_id == stranger["data"]["object"]["id"]
                )
            )
    assert kept is not None
    assert (kept.outcome, kept.for_workspace_id, kept.detail) == (
        "ignored",
        None,
        {"why": "no_workspace"},
    )
    assert invoices is None


# ── read again from Stripe's API ────────────────────────────────────────────


class StripeHistory(FakeStripe):
    """Stripe's lists of invoices and charges too, two by page."""

    def __init__(self) -> None:
        super().__init__()
        self.lists: dict[str, list[dict[str, Any]]] = {"/v1/invoices": [], "/v1/charges": []}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        listed = self.lists.get(request.url.path)
        if request.method != "GET" or listed is None:
            return super().__call__(request)
        self.asked.append((request.method, request.url.path, dict(request.url.params)))
        after = request.url.params.get("starting_after")
        start = next(i + 1 for i, item in enumerate(listed) if item["id"] == after) if after else 0
        return httpx.Response(
            200, json={"data": listed[start : start + 2], "has_more": start + 2 < len(listed)}
        )


@pytest.mark.integration
async def test_what_the_webhooks_missed_is_read_again_every_page_once(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    workspace = await _subscribed(client, identity, acme, stripe)
    history = StripeHistory()
    invoices = [f"in_{uuid.uuid4().hex[:10]}" for _ in range(3)]
    history.lists["/v1/invoices"] = [
        _invoice(invoices[0], "paid", amount_paid=21480, amount_remaining=0),
        _invoice(invoices[1], "void"),
        _invoice(invoices[2], "draft"),
    ]
    charge = f"ch_{uuid.uuid4().hex[:10]}"
    history.lists["/v1/charges"] = [
        _charge(charge, invoices[0], 2000, at=1_800_000_900),
        _charge(f"ch_{uuid.uuid4().hex[:10]}", invoices[0], 0, at=1_800_000_900),
    ]
    now = datetime.now(UTC)
    done = await read_history(history.client(), now=now, only=workspace)
    assert done == {"customers": 1, "invoices": 3, "refunds": 1, "unreadable": 0}
    asked = [params for _, path, params in history.asked if path == "/v1/invoices"]
    assert [p.get("starting_after") for p in asked] == [None, invoices[1]]
    assert {p["customer"] for p in asked} == {"cus_1"}

    kept = await _rows(BillingInvoice, workspace, BillingInvoice.stripe_invoice_id)
    assert sorted((i.stripe_invoice_id, i.status, i.said_by) for i in kept) == sorted(
        [
            (invoices[0], "paid", "sync"),
            (invoices[1], "void", "sync"),
            (invoices[2], "draft", "sync"),
        ]
    )
    assert [p.reference for p in await _rows(BillingPayment, workspace, BillingPayment.at)] == [
        f"{invoices[0]}:paid"
    ]
    # Read again: the same rows, nothing more.
    await read_history(history.client(), now=now, only=workspace)
    assert len(await _rows(BillingInvoice, workspace, BillingInvoice.issued_at)) == 3
    assert len(await _rows(BillingPayment, workspace, BillingPayment.at)) == 1
    assert len(await _rows(BillingRefund, workspace, BillingRefund.at)) == 1


@pytest.mark.integration
async def test_each_subscription_is_set_beside_stripes_every_difference_said(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    stripe: FakeStripe,
) -> None:
    workspace = await _subscribed(client, identity, acme, stripe)
    at = datetime.now(UTC)
    same = await reconcile(stripe.client(), at=at, only=workspace)
    assert same == {
        "subscriptions": 1,
        "unreadable": 0,
        "mrr_cents": {"leka": 17900, "stripe": 17900},
        "mrr_unknown": {"leka": 0, "stripe": 0},
        "differences": [],
    }
    # Changed in Stripe, its event not received yet: said, never fixed.
    stripe.subscriptions["sub_1"] = _priced(subscription("business", "active"), 39900)
    differs = await reconcile(stripe.client(), at=at, only=workspace)
    assert differs["mrr_cents"] == {"leka": 17900, "stripe": 39900}
    assert [(d["field"], d["leka"], d["stripe"]) for d in differs["differences"]] == [
        ("mrr", 17900, 39900),
        ("plan", "growth", "business"),
    ]
    assert {
        (d["organisation"], d["subscription"], d["source"]) for d in differs["differences"]
    } == {(str(workspace), "sub_1", "plan")}
    with system_scope():
        async with session_factory() as session:
            account = await session.scalar(
                select(BillingAccount).where(BillingAccount.workspace_id == workspace)
            )
    assert account is not None and account.plan == "growth"
