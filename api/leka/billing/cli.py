"""LEKA's own billing commands (LEKA-431) — on the server, never over HTTP.

python -m leka.billing.cli stripe-sync
    Every product, price and the launch coupon the catalogue needs,
    created in the Stripe account of LEKA_STRIPE_SECRET_KEY — test or
    live — those missing only. Prints each price's lookup key and id.
    Run once per environment, then after each catalogue change.

python -m leka.billing.cli grant-agents <workspace> --by NAME --reason WHY
    Every agent, for this workspace — LEKA's team's, for tests (2026-10-14).
    Kept, said who and why. `--end` takes it back.

python -m leka.billing.cli amounts [--all]
    The recurring price of every subscription still paying, read once from
    Stripe (LEKA-548): those subscribed before LEKA kept it, or an add-on
    bought before its subscription's first event. Only GETs to Stripe, and
    only the price is written: a subscription's state stays the webhook's.
    `--all` reads again those already known. Prints what it filled.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from leka.billing.catalogue import catalogue
from leka.billing.entitlements import EVERY, end, grant
from leka.billing.models import AgentEntitlement, BillingAccount
from leka.billing.revenue import recurring_of
from leka.billing.stripe import Stripe, StripeError
from leka.billing.subscriptions import PAYING, BillingUnavailableError, stripe
from leka.billing.sync import sync
from leka.db import load_schema, session_factory, system_scope, workspace_scope


async def _sync() -> int:
    try:
        client = stripe()
    except BillingUnavailableError:
        sys.stderr.write("LEKA_STRIPE_SECRET_KEY is not set.\n")
        return 2
    done = await sync(client, catalogue(), today=datetime.now(UTC).date())
    sys.stdout.write(
        json.dumps(
            {"created": done.created, "prices": done.prices, "coupon": done.coupon}, indent=2
        )
        + "\n"
    )
    return 0


async def _grant(workspace: uuid.UUID, *, by: str, reason: str, take_back: bool) -> int:
    with workspace_scope(workspace):
        async with session_factory() as session:
            said: dict[str, object]
            if take_back:
                said = {"ended": await end(session, workspace, key=EVERY)}
            else:
                row = await grant(session, workspace, by=by, reason=reason)
                said = {"granted": str(row.id), "since": row.started_at.isoformat()}
            await session.commit()
    sys.stdout.write(json.dumps({"workspace": str(workspace), **said}) + "\n")
    return 0


async def fill_amounts(client: Stripe, *, every: bool = False) -> dict[str, int]:
    """Each paying subscription's recurring price, from Stripe, where LEKA
    does not know it yet (or again, `every`)."""
    with system_scope():
        async with session_factory() as session:
            plans = (
                await session.execute(
                    select(
                        BillingAccount.workspace_id, BillingAccount.stripe_subscription_id
                    ).where(
                        BillingAccount.stripe_subscription_id.is_not(None),
                        BillingAccount.status.in_(PAYING),
                        *([] if every else [BillingAccount.recurring.is_(None)]),
                    )
                )
            ).all()
            add_ons = (
                await session.execute(
                    select(AgentEntitlement.workspace_id, AgentEntitlement.stripe_subscription_id)
                    .where(
                        AgentEntitlement.origin == "purchase",
                        AgentEntitlement.status == "active",
                        AgentEntitlement.stripe_subscription_id.is_not(None),
                        *([] if every else [AgentEntitlement.recurring.is_(None)]),
                    )
                    .distinct()
                )
            ).all()
    done = {"filled": 0, "not_fixed": 0, "unreadable": 0}
    kept: tuple[tuple[type[BillingAccount] | type[AgentEntitlement], Sequence[Any]], ...] = (
        (BillingAccount, plans),
        (AgentEntitlement, add_ons),
    )
    for model, rows in kept:
        for workspace_id, subscription in rows:
            try:
                said = await client.get(f"/v1/subscriptions/{subscription}")
            except StripeError:
                done["unreadable"] += 1
                continue
            recurring = recurring_of(said)
            if recurring is None:
                done["not_fixed"] += 1
                continue
            with workspace_scope(workspace_id):
                async with session_factory() as session:
                    await session.execute(
                        update(model)
                        .where(
                            model.workspace_id == workspace_id,
                            model.stripe_subscription_id == subscription,
                        )
                        .values(recurring=recurring)
                    )
                    await session.commit()
            done["filled"] += 1
    return done


async def _amounts(every: bool) -> int:
    try:
        client = stripe()
    except BillingUnavailableError:
        sys.stderr.write("LEKA_STRIPE_SECRET_KEY is not set.\n")
        return 2
    sys.stdout.write(json.dumps(await fill_amounts(client, every=every)) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m leka.billing.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stripe-sync", help="the catalogue's products and prices, in Stripe")
    granting = commands.add_parser("grant-agents", help="every agent, for one workspace")
    granting.add_argument("workspace", type=uuid.UUID)
    granting.add_argument("--by", required=True)
    granting.add_argument("--reason", required=True)
    granting.add_argument("--end", action="store_true", help="take it back")
    amounts = commands.add_parser("amounts", help="each paying subscription's price, from Stripe")
    amounts.add_argument("--all", action="store_true", help="read again those already known")
    said = parser.parse_args(argv)
    if said.command == "amounts":
        return asyncio.run(_amounts(said.all))
    if said.command == "grant-agents":
        return asyncio.run(
            _grant(said.workspace, by=said.by, reason=said.reason, take_back=said.end)
        )
    return asyncio.run(_sync())


if __name__ == "__main__":
    load_schema()
    raise SystemExit(main())
