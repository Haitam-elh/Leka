"""Buying an agent, or a bundle of them (2026-10-14, the product call): a
monthly subscription of its own, beside the plan's — never instead of it.

    checkout_add_on()   a Stripe Checkout at the catalogue's price — the
                        agent's tier, the bundle's — refused on a plan that
                        runs no agent (Free), or for what is already owned.
                        Opened from an intention's decision, the agents
                        chosen there are kept, launched once it is paid.
    apply_add_on()      what Stripe's verified events change: paid, it is
                        owned (an entitlement, its subscription said);
                        cancelled or unpaid, no longer. The plan is never
                        touched by an add-on's events.

What a person buys is what the page shows: the amount comes from
catalogue.yaml, sent as the line's price — no price id configured anywhere.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import JobQueue, enqueue_job
from leka.billing.catalogue import catalogue
from leka.billing.entitlements import end, grant, owned, plan_runs_agents
from leka.billing.models import AddOnCheckout
from leka.billing.stripe import Stripe
from leka.billing.subscriptions import CheckoutRefusedError, _customer, account_of
from leka.core.config import settings

logger = structlog.get_logger(__name__)

# Once paid, the agents chosen at an intention's decision are launched: the
# intentions' job, by its dotted path — billing never imports them.
LAUNCH_JOB = "leka.intentions.agents.run_bought_launch"
# Stripe's subscription statuses that keep an add-on.
ENDING = frozenset({"canceled", "unpaid", "incomplete_expired"})
# The events that grant an option, once its payment is confirmed.
GRANTING = frozenset({"checkout.session.completed", "checkout.session.async_payment_succeeded"})
PAID = frozenset({"paid", "no_payment_required"})


@dataclass(frozen=True)
class AddOn:
    kind: str  # agent, bundle
    key: str
    monthly_price: int  # cents
    agents: tuple[str, ...]


def add_on(kind: str, key: str) -> AddOn | None:
    """What the catalogue sells under this kind and key."""
    sold = catalogue().add_ons
    if kind == "agent" and key in sold.agents:
        return AddOn("agent", key, sold.prices[key], (key,))
    bundle = sold.bundle(key) if kind == "bundle" else None
    # Sold only once every agent it names is (LEKA-454).
    if bundle is not None and bundle.sellable:
        return AddOn("bundle", key, bundle.monthly_price, bundle.agents)
    return None


async def checkout_add_on(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    kind: str,
    key: str,
    name: str,
    by: uuid.UUID,
    client: Stripe,
    intention_id: uuid.UUID | None = None,
    launch: Sequence[Mapping[str, Any]] = (),
    locale: str = "fr",
) -> str:
    """A Checkout for an agent or a bundle — its URL. CheckoutRefusedError
    when it cannot be bought here."""
    sold = catalogue().add_ons
    found = add_on(kind, key)
    if not sold.available or found is None:
        raise CheckoutRefusedError("not_sold", "This agent or bundle is not sold.")
    has = await owned(session, workspace_id)
    if not has.every and not plan_runs_agents(has.plan):
        raise CheckoutRefusedError(
            "plan_required", f"Agents run from the {sold.minimum_plan.title()} plan."
        )
    if has.every or all(a in has.agents or a in has.included for a in found.agents):
        raise CheckoutRefusedError("owned", "Already owned here.")
    account = await account_of(session, workspace_id)
    customer = await _customer(client, account)
    marks = {
        "workspace_id": str(workspace_id),
        "leka_add_on_kind": found.kind,
        "leka_add_on_key": found.key,
    }
    back = (
        f"{settings.web_url}/intentions/{intention_id}/decision"
        if intention_id is not None
        else f"{settings.web_url}/capabilities"
    )
    made = await client.post(
        "/v1/checkout/sessions",
        {
            "mode": "subscription",
            "customer": customer,
            "client_reference_id": str(workspace_id),
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": catalogue().currency.lower(),
                        "unit_amount": found.monthly_price,
                        "recurring": {"interval": "month"},
                        "tax_behavior": "exclusive",
                        "product_data": {"name": name, "metadata": marks},
                    },
                }
            ],
            "subscription_data": {"metadata": marks},
            "payment_method_collection": "always",
            "metadata": marks,
            "locale": locale,
            "success_url": f"{back}?bought={found.key}",
            "cancel_url": f"{back}?bought=cancelled",
        },
    )
    session.add(
        AddOnCheckout(
            workspace_id=workspace_id,
            stripe_session_id=str(made["id"]),
            kind=found.kind,
            key=found.key,
            requested_by=by,
            intention_id=intention_id,
            launch=[dict(each) for each in launch],
        )
    )
    await session.commit()
    return str(made["url"])


def marked(data: Mapping[str, Any]) -> tuple[str, str] | None:
    """The add-on a Stripe object is about, by its marks — None when it is
    the plan's."""
    marks = data.get("metadata") or {}
    key, kind = marks.get("leka_add_on_key"), marks.get("leka_add_on_kind")
    return (str(kind), str(key)) if key and kind else None


async def apply_add_on(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    kind: str,
    data: Mapping[str, Any],
    *,
    made: datetime,
) -> str:
    """What one of an add-on's events changes."""
    found = marked(data)
    if found is None:
        return "ignored"
    what, key = found
    if kind in GRANTING:
        # Granted only once Stripe says it is paid (LEKA-454): a payment
        # still processing is granted by its async_payment_succeeded.
        if str(data.get("payment_status") or "") not in PAID:
            return "not_paid"
        subscription = str(data.get("subscription") or "") or None
        await grant(
            session,
            workspace_id,
            key=key,
            kind=what,
            origin="purchase",
            by="stripe",
            reason=f"Stripe {subscription}",
            subscription=subscription,
            now=made,
        )
        row = await session.scalar(
            select(AddOnCheckout).where(AddOnCheckout.stripe_session_id == str(data.get("id")))
        )
        if row is not None:
            row.status = "paid"
        return f"add_on:{what}:{key}"
    if kind.startswith("customer.subscription."):
        status = str(data.get("status") or "")
        # Ended only by a status that ends it: an event delivered late — the
        # subscription « incomplete » as it was made, before its payment —
        # never takes back what its paid checkout granted.
        if kind.endswith(".deleted") or status in ENDING:
            ended = await end(session, workspace_id, subscription=str(data.get("id") or ""))
            return f"add_on_ended:{ended}"
        return "add_on_kept"
    return "ignored"


async def launch_bought(session: AsyncSession, workspace_id: uuid.UUID, session_id: str) -> bool:
    """Once its payment is kept: the agents chosen at an intention's decision,
    launched — by the intentions' job. True when one was queued."""
    row = await session.scalar(
        select(AddOnCheckout).where(AddOnCheckout.stripe_session_id == session_id)
    )
    if row is None or row.status != "paid" or row.intention_id is None or not row.launch:
        return False
    queued = await enqueue_job(
        LAUNCH_JOB,
        str(workspace_id),
        str(row.id),
        for_workspace_id=workspace_id,
        queue=JobQueue.HIGH,
        concurrency_key=f"bought-launch:{row.id}",
    )
    return queued is not None
