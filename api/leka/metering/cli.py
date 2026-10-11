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

    python -m leka.metering.cli plan WORKSPACE_ID PLAN --by NAME --reason TEXT
            [--credits N]
        The workspace on PLAN (free, starter, growth, business, enterprise)
        from now on — --credits: its credits a month, the plan's overridden
        (an Enterprise contract). Kept, and in the workspace's audit trail.

    python -m leka.metering.cli plans WORKSPACE_ID
        Every plan it was on, the latest first.

    python -m leka.metering.cli pack WORKSPACE_ID CREDITS --by NAME --reason TEXT
        Credits added to this month, gone when it ends. Kept and audited.

    python -m leka.metering.cli credits WORKSPACE_ID
        Its plan and its AI credits this month — as JSON.

    python -m leka.metering.cli workspaces
        Every workspace, its id and its plan now.

    python -m leka.metering.cli report NAME [--month 2026-10] [--format csv|json]
        LEKA's internal reports, across workspaces (docs/metering.md § 6):
        agents (runs, cost avg/P50/P90/P95), intentions (by month, the same),
        workspaces, plans (cost, credits used, margin at list and promo
        price), waste (invalid answers, retries), context (tokens a call).

    python -m leka.metering.cli compare --before 2026-10-01:2026-10-15
            --after 2026-10-15:2026-11-01 [--format csv|json]
        Two periods side by side, by agent and purpose — before and after an
        optimisation.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from leka.capabilities import ModelRate
from leka.db import load_schema, session_factory, system_scope, workspace_scope
from leka.governance import PlanError, add_pack, plans, set_plan
from leka.metering import reports
from leka.metering.credits import credits_now
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


async def _plan(given: argparse.Namespace) -> int:
    workspace_id = uuid.UUID(given.workspace)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            try:
                row = await set_plan(
                    session,
                    workspace_id,
                    given.plan,
                    by=given.by,
                    reason=given.reason,
                    monthly_credits=given.credits,
                )
            except PlanError as error:
                sys.stderr.write(f"{error}\n")
                return 1
            await session.commit()
    sys.stdout.write(f"{row.plan} from {row.at.isoformat()}\n")
    return 0


async def _plans(workspace: str) -> int:
    workspace_id = uuid.UUID(workspace)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await plans(session, workspace_id)
    for row in rows:
        own = "" if row.monthly_credits is None else f" ({row.monthly_credits} credits)"
        sys.stdout.write(f"{row.at.isoformat()}  {row.plan}{own}  by {row.set_by} — {row.reason}\n")
    if not rows:
        sys.stdout.write("free — never set\n")
    return 0


async def _pack(given: argparse.Namespace) -> int:
    workspace_id = uuid.UUID(given.workspace)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            try:
                row = await add_pack(
                    session, workspace_id, given.credits, by=given.by, reason=given.reason
                )
            except PlanError as error:
                sys.stderr.write(f"{error}\n")
                return 1
            await session.commit()
    sys.stdout.write(f"+{row.credits} credits for {row.period.isoformat()[:7]}\n")
    return 0


async def _credits(workspace: str) -> int:
    workspace_id = uuid.UUID(workspace)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            read = await credits_now(session, workspace_id, now=datetime.now(UTC))
    sys.stdout.write(read.model_dump_json(indent=2) + "\n")
    return 0


def _write(rows: list[dict[str, object]], fmt: str) -> None:
    if fmt == "json":
        sys.stdout.write(json.dumps(rows, indent=2, default=str) + "\n")
        return
    out = csv.DictWriter(sys.stdout, fieldnames=reports.columns(rows) or ["empty"])
    out.writeheader()
    out.writerows(rows)


def _period(text: str) -> tuple[date, date]:
    start, _, end = text.partition(":")
    return date.fromisoformat(start), date.fromisoformat(end)


async def _report(name: str, month: str | None, fmt: str) -> int:
    first = date.fromisoformat(f"{month}-01") if month else None
    with system_scope():
        async with session_factory() as session:
            if name == "plans":
                rows = await reports.plans(session, month=first)
            else:
                rows = await reports.report(session, name, month=first)
    _write(rows, fmt)
    return 0


async def _compare(before: str, after: str, fmt: str) -> int:
    with system_scope():
        async with session_factory() as session:
            rows = await reports.compare(session, _period(before), _period(after))
    _write(rows, fmt)
    return 0


async def _workspaces() -> int:
    with system_scope():
        async with session_factory() as session:
            rows = await reports.workspaces(session)
    for row in rows:
        sys.stdout.write(f"{row['id']}  {row['plan']:<10}  {row['name']}\n")
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
    plan = commands.add_parser("plan")
    plan.add_argument("workspace")
    plan.add_argument("plan")
    plan.add_argument("--by", required=True)
    plan.add_argument("--reason", required=True)
    plan.add_argument("--credits", type=int)
    history = commands.add_parser("plans")
    history.add_argument("workspace")
    pack = commands.add_parser("pack")
    pack.add_argument("workspace")
    pack.add_argument("credits", type=int)
    pack.add_argument("--by", required=True)
    pack.add_argument("--reason", required=True)
    held = commands.add_parser("credits")
    held.add_argument("workspace")
    commands.add_parser("workspaces")
    reported = commands.add_parser("report")
    reported.add_argument("name", choices=[*reports.REPORTS, "plans"])
    reported.add_argument("--month")
    reported.add_argument("--format", choices=["csv", "json"], default="csv")
    compared = commands.add_parser("compare")
    compared.add_argument("--before", required=True)
    compared.add_argument("--after", required=True)
    compared.add_argument("--format", choices=["csv", "json"], default="csv")
    given = parser.parse_args(argv)
    if given.command == "workspaces":
        return asyncio.run(_workspaces())
    if given.command == "report":
        return asyncio.run(_report(given.name, given.month, given.format))
    if given.command == "compare":
        return asyncio.run(_compare(given.before, given.after, given.format))
    if given.command == "plan":
        return asyncio.run(_plan(given))
    if given.command == "plans":
        return asyncio.run(_plans(given.workspace))
    if given.command == "pack":
        return asyncio.run(_pack(given))
    if given.command == "credits":
        return asyncio.run(_credits(given.workspace))
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
