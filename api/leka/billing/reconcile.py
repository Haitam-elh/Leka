"""LEKA's money set against Stripe's (LEKA-554), Stripe the source of truth:
read again from its API, on the server, only GETs.

    read_history()   every invoice and every refunded charge of each
                     customer LEKA knows, kept as Stripe says them now
                     (history.py): what the webhooks missed, or what came
                     before LEKA kept them
    reconcile()      each subscription LEKA counts, a plan's or an
                     add-on's, beside Stripe's: its status, its plan, what
                     it brings in a month; the MRR both ways. A difference
                     is said, never fixed here: a subscription's state stays
                     the webhook's
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import select

from leka.billing.history import EARNING, keep_invoice, keep_refund, mrr_of
from leka.billing.models import AgentEntitlement, BillingAccount
from leka.billing.revenue import recurring_of
from leka.billing.stripe import Stripe, StripeError
from leka.db import session_factory, system_scope, workspace_scope

PAGE = 100
SUBSCRIBED = EARNING | {"trialing"}


async def _every(client: Stripe, path: str, params: list[tuple[str, str]]) -> AsyncIterator[Any]:
    """Every object of one of Stripe's lists, page after page."""
    after: str | None = None
    while True:
        said = await client.get(
            path,
            [*params, ("limit", str(PAGE)), *([("starting_after", after)] if after else [])],
        )
        data = said.get("data") or []
        for item in data:
            yield item
        if not said.get("has_more") or not data:
            return
        after = str(data[-1].get("id"))


def _only(column: Any, only: uuid.UUID | None) -> list[Any]:
    return [column == only] if only else []


async def _customers(only: uuid.UUID | None) -> list[tuple[uuid.UUID, str]]:
    with system_scope():
        async with session_factory() as session:
            return [
                (workspace_id, customer)
                for workspace_id, customer in (
                    await session.execute(
                        select(
                            BillingAccount.workspace_id, BillingAccount.stripe_customer_id
                        ).where(
                            BillingAccount.stripe_customer_id.is_not(None),
                            *_only(BillingAccount.workspace_id, only),
                        )
                    )
                ).tuples()
                if customer
            ]


async def read_history(
    client: Stripe, *, now: datetime, since: datetime | None = None, only: uuid.UUID | None = None
) -> dict[str, int]:
    """Each known customer's invoices and refunded charges, kept as Stripe
    says them now; `only`: one organisation's."""
    done = {"customers": 0, "invoices": 0, "refunds": 0, "unreadable": 0}
    created = [("created[gte]", str(int(since.timestamp())))] if since else []
    for workspace_id, customer in await _customers(only):
        try:
            invoices = [
                i async for i in _every(client, "/v1/invoices", [("customer", customer), *created])
            ]
            charges = [
                c async for c in _every(client, "/v1/charges", [("customer", customer), *created])
            ]
        except StripeError:
            done["unreadable"] += 1
            continue
        done["customers"] += 1
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                for invoice in invoices:
                    if await keep_invoice(
                        session, workspace_id, invoice, said_at=now, said_by="sync"
                    ):
                        done["invoices"] += 1
                for charge in charges:
                    if int(charge.get("amount_refunded") or 0) > 0 and await keep_refund(
                        session, workspace_id, charge, said_at=now
                    ):
                        done["refunds"] += 1
                await session.commit()
    return done


def _plan(subscription: dict[str, Any]) -> str | None:
    items = (subscription.get("items") or {}).get("data") or []
    price = (items[0].get("price") if items else None) or {}
    return (price.get("metadata") or {}).get("leka_plan") or (
        subscription.get("metadata") or {}
    ).get("leka_plan")


async def reconcile(
    client: Stripe, *, at: datetime, only: uuid.UUID | None = None
) -> dict[str, Any]:
    """Each subscription LEKA counts beside Stripe's, and the MRR both ways
    (euro cents a month): every difference said; `only`: one
    organisation's."""
    with system_scope():
        async with session_factory() as session:
            plans = (
                await session.scalars(
                    select(BillingAccount).where(
                        BillingAccount.stripe_subscription_id.is_not(None),
                        *_only(BillingAccount.workspace_id, only),
                    )
                )
            ).all()
            add_ons = (
                await session.scalars(
                    select(AgentEntitlement).where(
                        AgentEntitlement.origin == "purchase",
                        AgentEntitlement.stripe_subscription_id.is_not(None),
                        *_only(AgentEntitlement.workspace_id, only),
                    )
                )
            ).all()
    leka: dict[str, tuple[uuid.UUID, str, str | None, str | None, int | None]] = {}
    for account in plans:
        if account.stripe_subscription_id:
            leka[account.stripe_subscription_id] = (
                account.workspace_id,
                "plan",
                account.status,
                account.plan,
                mrr_of(account.recurring, at) if account.status in EARNING else 0,
            )
    for bought in add_ons:
        if bought.stripe_subscription_id and bought.stripe_subscription_id not in leka:
            active = bought.status == "active"
            leka[bought.stripe_subscription_id] = (
                bought.workspace_id,
                "add_on",
                "active" if active else "canceled",
                None,
                mrr_of(bought.recurring, at) if active else 0,
            )
    differences: list[dict[str, Any]] = []
    mrr = {"leka": 0, "stripe": 0}
    unknown = {"leka": 0, "stripe": 0}
    unreadable = 0
    for subscription_id, (workspace_id, source, status, plan, counted) in sorted(leka.items()):
        try:
            said = await client.get(f"/v1/subscriptions/{subscription_id}")
        except StripeError:
            unreadable += 1
            continue
        stripe_status = str(said.get("status") or "")
        earning = stripe_status in EARNING
        stripe_mrr = mrr_of(recurring_of(said), at) if earning else 0
        their = {"status": stripe_status, "mrr": stripe_mrr}
        ours: dict[str, Any] = {"status": status, "mrr": counted}
        if source == "plan":
            # On a plan while it earns or is tried; else Free, both ways.
            their["plan"] = (_plan(said) or "free") if stripe_status in SUBSCRIBED else "free"
            ours["plan"] = plan if status in SUBSCRIBED else "free"
        # An add-on ended in LEKA, ended in Stripe too: the same, whatever word.
        if source == "add_on" and status == "canceled" and not earning:
            their["status"] = "canceled"
        for field, value in ours.items():
            if value != their[field]:
                differences.append(
                    {
                        "organisation": str(workspace_id),
                        "subscription": subscription_id,
                        "source": source,
                        "field": field,
                        "leka": value,
                        "stripe": their[field],
                    }
                )
        for side, value in (("leka", counted), ("stripe", stripe_mrr)):
            if value is None:
                unknown[side] += 1
            else:
                mrr[side] += value
    return {
        "subscriptions": len(leka),
        "unreadable": unreadable,
        "mrr_cents": mrr,
        "mrr_unknown": unknown,
        "differences": differences,
    }


__all__ = ["read_history", "reconcile"]
