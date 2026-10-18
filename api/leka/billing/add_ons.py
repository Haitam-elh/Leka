"""Buying an agent, or a bundle of them (2026-10-14, the product call): a
monthly subscription of its own, beside the plan's — never instead of it.

    checkout_add_on()   a Stripe Checkout at the catalogue's price — the
                        agent's tier, the bundle's — refused on a plan that
                        runs no agent (Free), or for what is already owned.
                        Opened from an intention's decision, the agents
                        chosen there are kept, launched once it is paid.
    apply_add_on()      what Stripe's verified events change: paid, it is
                        owned (an entitlement, its subscription said);
                        cancelled or unpaid, no longer; its renewal as
                        Stripe says it. The plan is never touched by an
                        add-on's events.
    add_on_renewal()    « Annuler l'abonnement » / « Réactiver le
                        renouvellement » of one add-on's subscription
                        (LEKA-474): kept until its period's end either
                        way; only a subscription this workspace bought an
                        add-on with — never the plan's, never another's.

What a person buys is what the page shows: each agent and bundle is a
Stripe price made from catalogue.yaml by the catalogue sync, found by its
lookup key (LEKA-461) — no price id configured anywhere.
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
from leka.billing.entitlements import end, entitlements, grant, owned, plan_runs_agents
from leka.billing.models import AddOnCheckout, AgentEntitlement
from leka.billing.stripe import Stripe
from leka.billing.subscriptions import (
    CheckoutRefusedError,
    _customer,
    _period_end,
    _price,
    account_of,
)
from leka.billing.sync import add_on_lookup_key
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
    # agent, bundle; agents, bundles: several bought together in one
    # Checkout (LEKA-458, LEKA-500), `key` their keys comma-separated.
    kind: str
    key: str
    monthly_price: int  # cents
    agents: tuple[str, ...]


def _bundle_agents(key: str) -> tuple[str, ...]:
    bundle = catalogue().add_ons.bundle(key)
    return tuple(bundle.agents) if bundle is not None else ()


def _bundle_price(key: str) -> int:
    bundle = catalogue().add_ons.bundle(key)
    return bundle.monthly_price if bundle is not None else 0


def add_on(kind: str, key: str) -> AddOn | None:
    """What the catalogue sells under this kind and key."""
    sold = catalogue().add_ons
    if kind == "agent" and key in sold.agents:
        return AddOn("agent", key, sold.prices[key], (key,))
    if kind == "agents":
        keys = tuple(dict.fromkeys(k for k in key.split(",") if k))
        if len(keys) >= 2 and all(k in sold.agents for k in keys):
            return AddOn("agents", ",".join(keys), sum(sold.prices[k] for k in keys), keys)
        return None
    if kind == "bundles":
        keys = tuple(dict.fromkeys(k for k in key.split(",") if k))
        found = [sold.bundle(k) for k in keys]
        # Each on sale (LEKA-454), at least two: one is a bundle's own Checkout.
        if len(keys) < 2 or not all(b is not None and b.sellable for b in found):
            return None
        bundles = [b for b in found if b is not None]
        return AddOn(
            "bundles",
            ",".join(keys),
            sum(b.monthly_price for b in bundles),
            tuple(dict.fromkeys(a for b in bundles for a in b.agents)),
        )
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
    by: uuid.UUID,
    client: Stripe,
    intention_id: uuid.UUID | None = None,
    launch: Sequence[Mapping[str, Any]] = (),
    locale: str = "auto",
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
    mine = [a for a in found.agents if a in has.agents or a in has.included]
    # A bundle owned whole — one of several too —, or an agent — one of
    # several — already here: never paid twice.
    whole = [
        k
        for k in (found.key.split(",") if found.kind == "bundles" else [])
        if set(_bundle_agents(k)) <= set(mine)
    ]
    if (
        has.every
        or whole
        or (mine and found.kind not in ("bundle", "bundles"))
        or len(mine) == len(found.agents)
    ):
        raise CheckoutRefusedError("owned", "Already owned here.")
    account = await account_of(session, workspace_id)
    customer = await _customer(client, account)
    marks = {
        "workspace_id": str(workspace_id),
        "leka_add_on_kind": found.kind,
        "leka_add_on_key": found.key,
    }
    # Back where it was bought: the intention's page (LEKA-458), or the
    # catalogue.
    back = (
        f"{settings.web_url}/intentions/{intention_id}"
        if intention_id is not None
        else f"{settings.web_url}/capabilities"
    )
    prices = sold.prices
    # Each at its Stripe price, found by its lookup key (LEKA-461) — several
    # agents a line each, one subscription.
    if found.kind == "agents":
        lines = [add_on_lookup_key("agent", k, prices[k]) for k in found.agents]
    elif found.kind == "bundles":
        # Several bundles, a line each at its own price, one subscription (LEKA-500).
        lines = [add_on_lookup_key("bundle", k, _bundle_price(k)) for k in found.key.split(",")]
    else:
        lines = [add_on_lookup_key(found.kind, found.key, found.monthly_price)]
    items = [{"quantity": 1, "price": await _price(client, each)} for each in lines]
    made = await client.post(
        "/v1/checkout/sessions",
        {
            "mode": "subscription",
            "customer": customer,
            "client_reference_id": str(workspace_id),
            "line_items": items,
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
        # Several agents bought together: each its own right, one
        # subscription ending them all (LEKA-458).
        # Several bundles too, each its own (LEKA-500).
        each_of = {"agents": "agent", "bundles": "bundle"}
        for each_kind, each_key in (
            [(each_of[what], k) for k in key.split(",") if k] if what in each_of else [(what, key)]
        ):
            await grant(
                session,
                workspace_id,
                key=each_key,
                kind=each_kind,
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
        # Cancelled or renewed from Stripe's portal too: said as Stripe says it.
        # shortcut: no ordering of these events — a late older one can say an
        # older renewal until the next; upgrade with an applied_at like the plan's.
        for bought in await _bought(session, workspace_id, str(data.get("id") or "")):
            bought.cancel_at_period_end = bool(data.get("cancel_at_period_end"))
            bought.current_period_end = _period_end(dict(data)) or bought.current_period_end
        return "add_on_kept"
    return "ignored"


async def _bought(
    session: AsyncSession, workspace_id: uuid.UUID, subscription: str
) -> list[AgentEntitlement]:
    """What this workspace bought with this subscription, still owned."""
    return [
        row
        for row in await entitlements(session, workspace_id)
        if subscription and row.origin == "purchase" and row.stripe_subscription_id == subscription
    ]


async def add_on_renewal(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    subscription: str,
    *,
    renew: bool,
    client: Stripe,
) -> list[AgentEntitlement]:
    """Renewed at its period's end, or not — what it grants kept until then
    either way. CheckoutRefusedError when this workspace bought nothing with
    it: the plan's subscription, or another workspace's, is never touched."""
    rows = await _bought(session, workspace_id, subscription)
    if not rows:
        raise CheckoutRefusedError("not_subscribed", "No agent or bundle bought with it here.")
    made = await client.post(
        f"/v1/subscriptions/{subscription}", {"cancel_at_period_end": not renew}
    )
    for row in rows:
        row.cancel_at_period_end = bool(made.get("cancel_at_period_end"))
        row.current_period_end = _period_end(made) or row.current_period_end
    await session.commit()
    return rows


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
