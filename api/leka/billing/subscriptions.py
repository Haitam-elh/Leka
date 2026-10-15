"""Paying for LEKA CORE (LEKA-431, LEKA-446): Stripe Checkout for a plan,
the customer portal, and what Stripe's verified events change.

    checkout(plan, interval)    a Stripe Checkout session for a self-service
                                plan: the price found by its lookup key —
                                what the page shows — and the launch offer's
                                coupon when the workspace may take it: monthly,
                                the offer open, never subscribed before.
                                Never the annual discount and the coupon
                                together. Its trial (Growth, 14 days) for a
                                workspace never subscribed: a card taken, the
                                first charge when it ends unless cancelled
                                before. Already subscribed: the portal.
    portal()                    Stripe's customer portal: card, invoices, plan
                                change, cancellation — as its settings say
    receive(payload, signature) a webhook: believed only when its signature
                                holds; kept once by its id — a delivery
                                repeated is never applied twice; then:

        checkout.session.completed      subscription: its plan applied; a
                                        one-time payment: nothing — the AI
                                        capacity is never sold apart
        customer.subscription.*         the plan as Stripe says it now: active,
                                        trialing or past_due keep it; unpaid,
                                        canceled, expired — a trial cancelled
                                        before its end too: back to Free — an
                                        event older than the last applied
                                        never undoes it
        invoice.paid / payment_failed   said on the account
        charge.refunded                 kept, for a person to decide

A plan comes only from a verified event — never from a browser coming back
from Checkout. The plan itself is leka.governance's (set_plan, LEKA-430):
audited, its credits the plan's each month.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing.catalogue import Catalogue, Interval, Quote, catalogue, quote
from leka.billing.models import BillingAccount, StripeEvent
from leka.billing.stripe import SignatureError, Stripe, StripeError, verify
from leka.billing.sync import coupon_id, lookup_key, portal_configuration
from leka.core.config import settings
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import plan_of, set_plan

logger = structlog.get_logger(__name__)

# Stripe's subscription statuses that keep the plan paid for: past_due is
# the grace while Stripe retries a failed payment.
PAYING = frozenset({"active", "trialing", "past_due"})
STRIPE = "stripe"


class BillingUnavailableError(Exception):
    """No Stripe key configured here: nothing can be bought."""


class CheckoutRefusedError(Exception):
    """Why a checkout cannot be opened: said by its code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def payments_open() -> bool:
    """Whether Stripe is configured here: plans can be bought."""
    return settings.stripe_secret_key is not None


def stripe() -> Stripe:
    key = settings.stripe_secret_key
    if key is None:
        raise BillingUnavailableError("Stripe is not configured.")
    return Stripe(key.get_secret_value(), base_url=settings.stripe_api_url)


async def account_of(session: AsyncSession, workspace_id: uuid.UUID) -> BillingAccount:
    """The workspace's billing account — made the first time it is asked."""
    found = await session.scalar(
        select(BillingAccount).where(BillingAccount.workspace_id == workspace_id)
    )
    if found is not None:
        return found
    account = BillingAccount(workspace_id=workspace_id, id=uuid.uuid4(), plan="free")
    session.add(account)
    await session.flush()
    return account


def launch_eligible(
    account: BillingAccount, offer: Catalogue, plan_key: str, interval: Interval, today: date
) -> bool:
    plan = offer.plan(plan_key)
    return (
        interval in offer.launch_offer.intervals
        and plan.launch_offer
        and offer.launch_open(today)
        and not account.launch_offer_used
    )


@dataclass(frozen=True)
class Checkout:
    url: str
    quote: Quote | None


async def _price(client: Stripe, key: str) -> str:
    found = await client.get("/v1/prices", [("lookup_keys[]", key), ("active", "true")])
    data = found.get("data") or []
    if not data:
        raise CheckoutRefusedError(
            "not_synced", "This price is not in Stripe yet: run the catalogue sync."
        )
    return str(data[0]["id"])


async def _customer(client: Stripe, account: BillingAccount) -> str:
    if account.stripe_customer_id:
        return account.stripe_customer_id
    made = await client.post(
        "/v1/customers",
        {"metadata": {"workspace_id": str(account.workspace_id)}},
        idempotency_key=f"leka-customer-{account.workspace_id}",
    )
    account.stripe_customer_id = str(made["id"])
    return account.stripe_customer_id


async def checkout(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    plan_key: str,
    interval: Interval,
    *,
    client: Stripe,
    today: date,
) -> Checkout:
    """A Stripe Checkout session for a self-service plan, at the price the
    catalogue says — CheckoutRefusedError otherwise."""
    offer = catalogue()
    try:
        plan = offer.plan(plan_key)
    except KeyError:
        raise CheckoutRefusedError("unknown_plan", "No such plan.") from None
    if not plan.self_service or not plan.monthly_price:
        raise CheckoutRefusedError("not_self_service", "This plan is not bought online.")
    if interval == "year" and not plan.annual:
        raise CheckoutRefusedError("not_sold", "This plan is not sold yearly.")
    account = await account_of(session, workspace_id)
    if account.status in PAYING and account.stripe_subscription_id:
        raise CheckoutRefusedError(
            "subscribed", "Already subscribed: change plan from the customer portal."
        )
    launch = launch_eligible(account, offer, plan.key, interval, today)
    # Once a workspace, like the launch offer: never subscribed before.
    trial = bool(plan.trial_days) and not account.launch_offer_used
    priced = quote(plan, interval, offer, today=today, launch=launch, trial=trial)
    price = await _price(client, lookup_key(plan, interval, offer, today=today))
    customer = await _customer(client, account)
    marks = {
        "workspace_id": str(workspace_id),
        "leka_plan": plan.key,
        "leka_interval": interval,
        "leka_launch": "yes" if launch else "no",
    }
    made = await client.post(
        "/v1/checkout/sessions",
        {
            "mode": "subscription",
            "customer": customer,
            "client_reference_id": str(workspace_id),
            "line_items": [{"price": price, "quantity": 1}],
            # The launch offer, or nothing: never stacked, no promotion codes.
            "discounts": [{"coupon": coupon_id(offer)}] if launch else None,
            "subscription_data": {
                "metadata": marks,
                # The card is taken now and charged when the trial ends —
                # cancelled before, nothing is; without a card, it ends.
                "trial_period_days": priced.trial_days,
                "trial_settings": {"end_behavior": {"missing_payment_method": "cancel"}}
                if trial
                else None,
            },
            "payment_method_collection": "always",
            "metadata": marks,
            "success_url": f"{settings.web_url}/billing?checkout=success",
            "cancel_url": f"{settings.web_url}/billing?checkout=cancelled",
        },
    )
    await session.commit()
    return Checkout(str(made["url"]), priced)


async def portal(session: AsyncSession, workspace_id: uuid.UUID, *, client: Stripe) -> str:
    account = await account_of(session, workspace_id)
    if not account.stripe_customer_id:
        raise CheckoutRefusedError("no_customer", "Nothing was ever bought here.")
    made = await client.post(
        "/v1/billing_portal/sessions",
        {
            "customer": account.stripe_customer_id,
            "return_url": f"{settings.web_url}/billing",
            # LEKA's own settings (sync.py), when they were made.
            "configuration": await portal_configuration(client),
        },
    )
    return str(made["url"])


# ── what Stripe says ────────────────────────────────────────────────────────


def _moment(seconds: object) -> datetime | None:
    return datetime.fromtimestamp(int(str(seconds)), UTC) if seconds else None


def _plan_of(subscription: dict[str, Any]) -> tuple[str | None, str | None]:
    items = (subscription.get("items") or {}).get("data") or []
    price = (items[0].get("price") if items else None) or {}
    metadata = price.get("metadata") or {}
    plan = metadata.get("leka_plan") or (subscription.get("metadata") or {}).get("leka_plan")
    interval = (price.get("recurring") or {}).get("interval")
    return plan, interval


async def _apply_subscription(
    session: AsyncSession, account: BillingAccount, subscription: dict[str, Any], made: datetime
) -> str:
    if account.applied_at is not None and made < account.applied_at:
        return "stale"
    status = str(subscription.get("status") or "")
    plan, interval = _plan_of(subscription)
    paying = status in PAYING and plan is not None
    said = str(subscription.get("id") or "") or None
    # A subscription never paid — a declined checkout's, expired a day later —
    # changes nothing: not the plan, not the one paid for.
    if not paying and said != account.stripe_subscription_id:
        return "ignored"
    account.stripe_subscription_id = said
    account.stripe_customer_id = (
        account.stripe_customer_id or str(subscription.get("customer") or "") or None
    )
    account.status = status
    account.interval = interval if paying else None
    account.current_period_end = _moment(subscription.get("current_period_end"))
    account.cancel_at_period_end = bool(subscription.get("cancel_at_period_end"))
    # Subscribed once: the launch offer is had.
    account.launch_offer_used = True
    account.applied_at = made
    wanted = plan if paying and plan else "free"
    account.plan = wanted
    now = await plan_of(session, account.workspace_id)
    if now.name != wanted:
        await set_plan(
            session,
            account.workspace_id,
            wanted,
            by=STRIPE,
            reason=f"Stripe {account.stripe_subscription_id}: {status}",
        )
    return f"plan:{wanted}"


async def _workspace_of(session: AsyncSession, data: dict[str, Any]) -> uuid.UUID | None:
    said = data.get("client_reference_id") or (data.get("metadata") or {}).get("workspace_id")
    if said:
        try:
            return uuid.UUID(str(said))
        except ValueError:
            return None
    customer = data.get("customer")
    if not customer:
        return None
    with system_scope():
        found = await session.scalar(
            select(BillingAccount.workspace_id).where(
                BillingAccount.stripe_customer_id == str(customer)
            )
        )
    return found


async def _apply(
    session: AsyncSession, event: dict[str, Any], workspace_id: uuid.UUID, client: Stripe | None
) -> str:
    kind = str(event.get("type"))
    data: dict[str, Any] = (event.get("data") or {}).get("object") or {}
    made = _moment(event.get("created")) or datetime.now(UTC)
    # An agent's or a bundle's (2026-10-14): its own, never the plan's.
    from leka.billing.add_ons import apply_add_on, marked

    if marked(data) is not None:
        return await apply_add_on(session, workspace_id, kind, data, made=made)
    account = await account_of(session, workspace_id)
    if kind == "checkout.session.completed":
        if data.get("mode") == "subscription" and data.get("subscription"):
            if client is None:
                raise BillingUnavailableError("Stripe is not configured.")
            subscription = await client.get(f"/v1/subscriptions/{data['subscription']}")
            account.stripe_customer_id = str(data.get("customer") or "") or None
            return await _apply_subscription(session, account, subscription, made)
        # A one-time payment buys nothing: no AI capacity is sold (LEKA-446).
        return "ignored"
    if kind.startswith("customer.subscription."):
        return await _apply_subscription(session, account, data, made)
    if kind in ("invoice.paid", "invoice.payment_failed"):
        account.last_invoice = kind.removeprefix("invoice.")
        return account.last_invoice
    if kind == "charge.refunded":
        # A refund is a person's decision; what it undoes, theirs too.
        return "refund_kept"
    return "ignored"


async def receive(
    payload: bytes, signature: str, *, now: datetime, client: Stripe | None = None
) -> str:
    """One webhook delivery: verified, kept once, applied. Raises
    SignatureError when it is not Stripe's; anything else that fails rolls
    back — the event is not kept, and Stripe delivers it again."""
    secret = settings.stripe_webhook_secret
    if secret is None:
        raise SignatureError("no webhook secret configured")
    event = verify(payload, signature, secret.get_secret_value(), now=int(now.timestamp()))
    event_id, kind = str(event.get("id") or ""), str(event.get("type") or "")
    if not event_id:
        raise SignatureError("no event id")
    data: dict[str, Any] = (event.get("data") or {}).get("object") or {}
    with system_scope():
        async with session_factory() as session:
            seen = await session.scalar(
                select(StripeEvent.id).where(StripeEvent.event_id == event_id)
            )
            if seen is not None:
                return "duplicate"
            workspace_id = await _workspace_of(session, data)
    if workspace_id is None:
        with system_scope():
            async with session_factory() as session:
                session.add(
                    StripeEvent(
                        event_id=event_id,
                        type=kind[:80],
                        outcome="ignored",
                        detail={"why": "no_workspace"},
                        received_at=now,
                    )
                )
                try:
                    await session.commit()
                except IntegrityError:
                    return "duplicate"
        return "ignored"
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            # Kept first: a delivery racing this one stops on its id.
            session.add(
                StripeEvent(
                    event_id=event_id,
                    type=kind[:80],
                    for_workspace_id=workspace_id,
                    outcome="applied",
                    received_at=now,
                )
            )
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                return "duplicate"
            said = await _apply(session, event, workspace_id, client)
            row = await session.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
            if row is not None:
                row.outcome = "ignored" if said in ("ignored", "stale", "not_paid") else "applied"
                row.detail = {"said": said}
            await session.commit()
            if kind == "checkout.session.completed" and said.startswith("add_on:"):
                from leka.billing.add_ons import launch_bought

                await launch_bought(session, workspace_id, str(data.get("id") or ""))
    logger.info("stripe_event_applied", stripe_event=event_id, type=kind, said=said)
    return said


__all__ = [
    "PAYING",
    "BillingUnavailableError",
    "Checkout",
    "CheckoutRefusedError",
    "StripeError",
    "account_of",
    "checkout",
    "launch_eligible",
    "payments_open",
    "portal",
    "receive",
    "stripe",
]
