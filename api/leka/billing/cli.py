"""LEKA's own billing commands (LEKA-431) — on the server, never over HTTP.

python -m leka.billing.cli stripe-sync
    Every product, price and the launch coupon the catalogue needs,
    created in the Stripe account of LEKA_STRIPE_SECRET_KEY — test or
    live — those missing only. Prints each price's lookup key and id.
    Run once per environment, then after each catalogue change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from leka.billing.catalogue import catalogue
from leka.billing.subscriptions import BillingUnavailableError, stripe
from leka.billing.sync import sync


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m leka.billing.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stripe-sync", help="the catalogue's products and prices, in Stripe")
    parser.parse_args(argv)
    return asyncio.run(_sync())


if __name__ == "__main__":
    raise SystemExit(main())
