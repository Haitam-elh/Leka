"""LEKA's own billing commands (LEKA-431) — on the server, never over HTTP.

python -m leka.billing.cli stripe-sync
    Every product, price and the launch coupon the catalogue needs,
    created in the Stripe account of LEKA_STRIPE_SECRET_KEY — test or
    live — those missing only. Prints each price's lookup key and id.
    Run once per environment, then after each catalogue change.

python -m leka.billing.cli grant-agents <workspace> --by NAME --reason WHY
    Every agent, for this workspace — LEKA's team's, for tests (2026-10-14).
    Kept, said who and why. `--end` takes it back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from leka.billing.catalogue import catalogue
from leka.billing.entitlements import EVERY, end, grant
from leka.billing.subscriptions import BillingUnavailableError, stripe
from leka.billing.sync import sync
from leka.db import load_schema, session_factory, workspace_scope


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m leka.billing.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stripe-sync", help="the catalogue's products and prices, in Stripe")
    granting = commands.add_parser("grant-agents", help="every agent, for one workspace")
    granting.add_argument("workspace", type=uuid.UUID)
    granting.add_argument("--by", required=True)
    granting.add_argument("--reason", required=True)
    granting.add_argument("--end", action="store_true", help="take it back")
    said = parser.parse_args(argv)
    if said.command == "grant-agents":
        return asyncio.run(
            _grant(said.workspace, by=said.by, reason=said.reason, take_back=said.end)
        )
    return asyncio.run(_sync())


if __name__ == "__main__":
    load_schema()
    raise SystemExit(main())
