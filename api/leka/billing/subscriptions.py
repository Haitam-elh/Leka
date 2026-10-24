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
                                change, cancellation — as its settings say —
                                in the person's language, never English by
                                default (2026-10-14: « Cancel subscription »)
    renewal(renew)              « Ne pas renouveler » / « Réactiver le
                                renouvellement »: the subscription kept until
                                its period's end, then not renewed — or renewed
                                again; nothing stops before that day
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

from leka.billing.catalogue import Catalogue, Interval, Plan, Quote, catalogue, quote
from leka.billing.models import BillingAccount, StripeEvent
from leka.billing.stripe import SignatureError, Stripe, StripeError, verify
from leka.billing.sync import (
    coupon_id,
    ensure_coupon,
    ensure_plan_price,
    ensure_portal,
    portal_configuration,
)
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


def stripe_locale(language: str | None) -> str:
    """The language Stripe's pages are shown in: the person's, when Stripe
    has it; else Stripe's own guess."""
    said = (language or "").split("-")[0].lower()
    return said if said in STRIPE_LOCALES else "auto"


# The languages Stripe's Checkout and portal speak.
STRIPE_LOCALES = frozenset(
    [
        "bg",
        "cs",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "fi",
        "fil",
        "fr",
        "hr",
        "hu",
        "id",
        "it",
        "ja",
        "ko",
        "lt",
        "lv",
        "ms",
        "mt",
        "nb",
        "nl",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sl",
        "sv",
        "th",
        "tr",
        "vi",
        "zh",
    ]
)


async def checkout(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    plan_key: str,
    interval: Interval,
    *,
    client: Stripe,
    today: date,
    intention_id: uuid.UUID | None = None,
    locale: str = "auto",
) -> Checkout:
    """A Stripe Checkout session for a self-service plan, at the price the
    catalogue says — CheckoutRefusedError otherwise. Opened from an
    intention (LEKA-458), Stripe brings the person back to it. Already
    subscribed: Stripe's confirmation of the change to that exact price
    (LEKA-490) — never a second subscription."""
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
        return await _change(client, account, plan, interval, offer, today=today, locale=locale)
    launch = launch_eligible(account, offer, plan.key, interval, today)
    # Once a workspace, like the launch offer: never subscribed before.
    trial = bool(plan.trial_days) and not account.launch_offer_used
    priced = quote(plan, interval, offer, today=today, launch=launch, trial=trial)
    # Made in Stripe when the catalogue changed since the last sync
    # (2026-10-24: no yearly price after the annual discount went to 30 %).
    price, _ = await ensure_plan_price(client, plan, interval, offer, today=today)
    if launch:
        await ensure_coupon(client, offer)
    customer = await _customer(client, account)
    marks = {
        "workspace_id": str(workspace_id),
        "leka_plan": plan.key,
        "leka_interval": interval,
        "leka_launch": "yes" if launch else "no",
    }
    back, flag = (
        (f"{settings.web_url}/intentions/{intention_id}", "activated")
        if intention_id is not None
        else (f"{settings.web_url}/billing", "checkout")
    )
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
            "locale": locale,
            "success_url": f"{back}?{flag}=success",
            "cancel_url": f"{back}?{flag}=cancelled",
        },
    )
    await session.commit()
    return Checkout(str(made["url"]), priced)


async def _change(
    client: Stripe,
    account: BillingAccount,
    plan: Plan,
    interval: Interval,
    offer: Catalogue,
    *,
    today: date,
    locale: str,
) -> Checkout:
    """Stripe's portal opened on the change to this plan's exact price
    (LEKA-490): what is prorated said by Stripe, confirmed there; the plan
    changes only with its event. The same plan and interval: refused."""
    if account.plan == plan.key and account.interval == interval:
        raise CheckoutRefusedError("same_plan", "Already on this plan.")
    price, _ = await ensure_plan_price(client, plan, interval, offer, today=today)
    # The portal confirms only a change to a price it lists: given every
    # price sold now (2026-10-24: monthly to yearly was refused).
    configuration, _ = await ensure_portal(client, offer, today=today)
    subscription = await client.get(f"/v1/subscriptions/{account.stripe_subscription_id}")
    items = (subscription.get("items") or {}).get("data") or []
    if not items:
        raise CheckoutRefusedError("not_subscribed", "No subscription to change.")
    made = await client.post(
        "/v1/billing_portal/sessions",
        {
            "customer": account.stripe_customer_id,
            "return_url": f"{settings.web_url}/billing/plans",
            "configuration": configuration,
            "locale": locale,
            "flow_data": {
                "type": "subscription_update_confirm",
                "subscription_update_confirm": {
                    "subscription": account.stripe_subscription_id,
                    "items": [{"id": items[0]["id"], "price": price, "quantity": 1}],
                },
                "after_completion": {
                    "type": "redirect",
                    "redirect": {"return_url": f"{settings.web_url}/billing?changed=success"},
                },
            },
        },
    )
    # What it costs from now on: never an offer for a first subscription.
    priced = quote(plan, interval, offer, today=today, launch=False, trial=False)
    return Checkout(str(made["url"]), priced)


async def portal(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    client: Stripe,
    locale: str = "auto",
    cancel: bool = False,
) -> str:
    """Stripe's customer portal — `cancel`: opened on ending the
    subscription at its period's end, the way back to Free (LEKA-490)."""
    account = await account_of(session, workspace_id)
    if not account.stripe_customer_id:
        raise CheckoutRefusedError("no_customer", "Nothing was ever bought here.")
    if cancel and not (account.stripe_subscription_id and account.status in PAYING):
        raise CheckoutRefusedError("not_subscribed", "No subscription to end.")
    made = await client.post(
        "/v1/billing_portal/sessions",
        {
            "customer": account.stripe_customer_id,
            "return_url": f"{settings.web_url}/billing",
            # LEKA's own settings (sync.py), when they were made.
            "configuration": await portal_configuration(client),
            "locale": locale,
            "flow_data": {
                "type": "subscription_cancel",
                "subscription_cancel": {"subscription": account.stripe_subscription_id},
            }
            if cancel
            else None,
        },
    )
    return str(made["url"])


async def renewal(
    session: AsyncSession, workspace_id: uuid.UUID, *, renew: bool, client: Stripe
) -> BillingAccount:
    """Renewed at its period's end, or not: the subscription kept until then
    either way — what Stripe answers kept at once, its event confirming it."""
    account = await account_of(session, workspace_id)
    if not account.stripe_subscription_id or account.status not in PAYING:
        raise CheckoutRefusedError("not_subscribed", "No subscription to renew or not.")
    made = await client.post(
        f"/v1/subscriptions/{account.stripe_subscription_id}",
        {"cancel_at_period_end": not renew},
    )
    account.cancel_at_period_end = bool(made.get("cancel_at_period_end"))
    account.current_period_end = _period_end(made) or account.current_period_end
    await session.commit()
    return account


# ── what Stripe says ────────────────────────────────────────────────────────


def _moment(seconds: object) -> datetime | None:
    return datetime.fromtimestamp(int(str(seconds)), UTC) if seconds else None


def _period_end(subscription: dict[str, Any]) -> datetime | None:
    """When its period ends: the subscription's word, or — Stripe's API from
    2025-03-31 on — its first item's (2026-10-14: a webhook endpoint on a
    newer version than LEKA's requests)."""
    said = subscription.get("current_period_end")
    if not said:
        items = (subscription.get("items") or {}).get("data") or []
        said = items[0].get("current_period_end") if items else None
    return _moment(said)


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
    account.current_period_end = _period_end(subscription)
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


async def _standing(session: AsyncSession, workspace_id: uuid.UUID) -> dict[str, Any]:
    """Where the workspace's subscription stands: what an event changed is
    said by comparing it before and after (LEKA-476)."""
    account = await session.scalar(
        select(BillingAccount).where(BillingAccount.workspace_id == workspace_id)
    )
    if account is None:
        return {"plan": "free", "cancel_at_period_end": False, "ends": None}
    return {
        "plan": account.plan,
        "cancel_at_period_end": account.cancel_at_period_end,
        "ends": account.current_period_end.isoformat() if account.current_period_end else None,
    }


def _changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What an applied event changed — the plan, the renewal — as
    [before, after], and when the period ends."""
    changed = {
        key: [before[key], after[key]]
        for key in ("plan", "cancel_at_period_end")
        if before[key] != after[key]
    }
    if not changed:
        return {}
    return {"changes": changed | ({"ends": after["ends"]} if after["ends"] else {})}


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
            before = await _standing(session, workspace_id)
            said = await _apply(session, event, workspace_id, client)
            after = await _standing(session, workspace_id)
            row = await session.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
            if row is not None:
                row.outcome = "ignored" if said in ("ignored", "stale", "not_paid") else "applied"
                # What it changed, kept with it: the notification centre
                # tells it from here (LEKA-476) — a renewal, a cancellation,
                # a plan — never from a guess.
                row.detail = (
                    {"said": said}
                    | _changes(before, after)
                    | (
                        {"reason": data.get("billing_reason")}
                        if kind.startswith("invoice.") and data.get("billing_reason")
                        else {}
                    )
                )
            await session.commit()
            if said.startswith("add_on:"):
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
