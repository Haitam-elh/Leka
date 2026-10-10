"""LEKA's own commands for metering (LEKA-430) — on the server, never over
HTTP: what they show crosses every workspace, and LEKA's costs are its own.

    python -m leka.metering.cli sweep [--since 2026-10-01]
        Every execution since then metered again — a backfill; without
        --since, the schedule's window. Idempotent.

    python -m leka.metering.cli intention WORKSPACE_ID INTENTION_ID
        What an intention cost, end to end, by step — as JSON.

    python -m leka.metering.cli rates
        Every model rate, oldest first.

    python -m leka.metering.cli rates add PROVIDER MODEL SINCE IN OUT
            [--cached PRICE] [--source TEXT]
        A rate from SINCE on (a day, YYYY-MM-DD), per million tokens in US
        dollars. A rate is never rewritten: a new price is a new rate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from leka.capabilities import ModelRate
from leka.db import load_schema, session_factory, system_scope, workspace_scope
from leka.metering.service import Metering, sweep


def _day(text: str) -> datetime:
    return datetime.combine(date.fromisoformat(text), datetime.min.time(), tzinfo=UTC)


async def _sweep(since: str | None) -> int:
    metered = await sweep(since=_day(since) if since else None)
    sys.stdout.write(
        json.dumps({"workspaces": len(metered), "executions": sum(metered.values())}) + "\n"
    )
    return 0


async def _intention(workspace: str, intention: str) -> int:
    workspace_id, intention_id = uuid.UUID(workspace), uuid.UUID(intention)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            cost = await Metering(session).intention_cost(
                workspace_id, intention_id, now=datetime.now(UTC)
            )
            await session.commit()
    sys.stdout.write(cost.model_dump_json(indent=2) + "\n")
    return 0


async def _rates() -> int:
    with system_scope():
        async with session_factory() as session:
            rows = (
                await session.scalars(
                    select(ModelRate).order_by(ModelRate.provider, ModelRate.model, ModelRate.since)
                )
            ).all()
    for row in rows:
        cached = "" if row.per_million_cached is None else f" cached {row.per_million_cached:g}"
        sys.stdout.write(
            f"{row.id}  {row.provider}/{row.model}  from {row.since}  "
            f"in {row.per_million_in:g} out {row.per_million_out:g}{cached}"
            f"  — {row.source or 'no source'}\n"
        )
    return 0


async def _add(given: argparse.Namespace) -> int:
    row = ModelRate(
        id=uuid.uuid4(),
        provider=given.provider,
        model=given.model,
        since=date.fromisoformat(given.since),
        per_million_in=given.per_in,
        per_million_out=given.per_out,
        per_million_cached=given.cached,
        source=given.source,
    )
    with system_scope():
        async with session_factory() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                sys.stderr.write("A rate of this model from this day exists already.\n")
                return 1
    sys.stdout.write(f"{row.id}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m leka.metering.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    swept = commands.add_parser("sweep")
    swept.add_argument("--since")
    intention = commands.add_parser("intention")
    intention.add_argument("workspace")
    intention.add_argument("intention")
    rates = commands.add_parser("rates")
    adding = rates.add_subparsers(dest="action")
    add = adding.add_parser("add")
    add.add_argument("provider")
    add.add_argument("model")
    add.add_argument("since")
    add.add_argument("per_in", type=float)
    add.add_argument("per_out", type=float)
    add.add_argument("--cached", type=float)
    add.add_argument("--source")
    given = parser.parse_args(argv)
    if given.command == "sweep":
        return asyncio.run(_sweep(given.since))
    if given.command == "intention":
        return asyncio.run(_intention(given.workspace, given.intention))
    if given.action == "add":
        if min(given.per_in, given.per_out, given.cached or 0) < 0:
            sys.stderr.write("A price is never negative.\n")
            return 1
        return asyncio.run(_add(given))
    return asyncio.run(_rates())


if __name__ == "__main__":
    load_schema()
    sys.exit(main())
