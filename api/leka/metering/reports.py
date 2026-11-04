"""LEKA's own reports on what its AI costs (LEKA-430) — across workspaces,
read from the metering views (migration 0a074280012e), by the server command
only: never over HTTP. Every cost is LEKA's, in US dollars, at the rates in
force; what is not known is said, never counted as 0.

    report()    a view, for a month: agents, intentions, workspaces, waste,
                context
    plans()     by plan: workspaces, what they cost LEKA, the credits used —
                and the margin at the list and the promotional price
    compare()   two periods side by side — before and after an
                optimisation: by agent or purpose, the cost of an execution,
                its calls, tokens, retries, invalid answers, and the change
    workspaces()  every workspace, its plan now
    usage()     every call to a model (LEKA-530), for the LEKA team only:
                its workspace, the person, the agent and the operation, the
                provider and the model, when, how it ended, its tokens in
                and out, its cost — in US dollars, on the rate it was priced
                with, said — and the AI credits it used; filtered by period,
                workspace, person, agent, provider, model, operation,
                status; or summed by any of them
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core.config import settings

# Each report: its view, and its order.
REPORTS: dict[str, tuple[str, str]] = {
    "agents": ("metering_agents", "cost_usd DESC NULLS LAST, agent"),
    "intentions": ("metering_intention_months", "month"),
    "workspaces": ("metering_workspace_months", "leka_cost_usd DESC NULLS LAST, workspace"),
    "waste": ("metering_waste", "invalid_cost_usd + retry_cost_usd DESC NULLS LAST, purpose"),
    "context": ("metering_context", "avg_tokens_in DESC NULLS LAST, purpose"),
}


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _rows(result: Any) -> list[dict[str, Any]]:
    return [{k: _plain(v) for k, v in row._mapping.items()} for row in result]


async def report(
    session: AsyncSession, name: str, *, month: date | None = None
) -> list[dict[str, Any]]:
    """One report's rows — for one month (its first day), or every month."""
    view, order = REPORTS[name]
    where = "WHERE month = :month" if month is not None else ""
    found = await session.execute(
        text(f"SELECT * FROM {view} {where} ORDER BY month, {order}"),  # noqa: S608 — names from REPORTS
        {"month": month} if month is not None else {},
    )
    return _rows(found)


def _margin(revenue: float | None, cost: float | None) -> float | None:
    if revenue is None or cost is None or revenue <= 0:
        return None
    return round((revenue - cost) / revenue, 4)


async def plans(session: AsyncSession, *, month: date | None = None) -> list[dict[str, Any]]:
    """By month and plan: the workspaces on it, what they cost LEKA, the
    credits they used — and, given the plan's prices, the revenue and the
    margin at the list price and at the promotional one."""
    found = await session.execute(
        text(
            "SELECT month, plan, count(*) AS workspaces, sum(executions) AS executions,"
            " sum(leka_cost_usd) AS leka_cost_usd,"
            " sum(workspace_cost_usd) AS workspace_cost_usd,"
            " sum(cost_not_known) AS cost_not_known"
            " FROM metering_workspace_months"
            " WHERE CAST(:month AS date) IS NULL OR month = :month"
            " GROUP BY month, plan ORDER BY month, plan"
        ),
        {"month": month},
    )
    rows = _rows(found)
    for row in rows:
        cost = row["leka_cost_usd"]
        row["credits_used"] = round(cost / settings.credit_usd, 2) if cost is not None else None
        row["avg_cost_per_workspace_usd"] = (
            round(cost / row["workspaces"], 6) if cost is not None else None
        )
        for kind, prices in (
            ("list", settings.plan_prices_usd),
            ("promo", settings.plan_promo_prices_usd),
        ):
            price = prices.get(row["plan"])
            revenue = round(price * row["workspaces"], 2) if price is not None else None
            row[f"{kind}_revenue_usd"] = revenue
            row[f"{kind}_margin"] = _margin(revenue, cost if cost is not None else 0.0)
    return rows


COMPARED = (
    "count(*) AS executions,"
    " avg(leka_cost_usd) AS avg_cost_usd,"
    " avg(calls) AS avg_calls,"
    " avg(tokens_in) AS avg_tokens_in,"
    " sum(retries)::double precision / NULLIF(sum(calls), 0) AS retry_rate,"
    " sum(invalid_calls)::double precision / NULLIF(sum(calls), 0) AS invalid_rate"
)
CHANGED = ("avg_cost_usd", "avg_calls", "avg_tokens_in", "retry_rate", "invalid_rate")


async def compare(
    session: AsyncSession,
    before: tuple[date, date],
    after: tuple[date, date],
) -> list[dict[str, Any]]:
    """Each subject — an agent, a purpose — in two periods, [start, end)
    each: what an execution cost and took, and the change in percent."""
    periods: dict[str, dict[str, dict[str, Any]]] = {}
    for label, (start, end) in (("before", before), ("after", after)):
        found = await session.execute(
            text(
                f"SELECT kind, subject, {COMPARED} FROM metering_executions"  # noqa: S608 — constants
                " WHERE started_at >= :start AND started_at < :end"
                " GROUP BY kind, subject"
            ),
            {"start": start, "end": end},
        )
        for row in _rows(found):
            key = f"{row.pop('kind')}:{row.pop('subject')}"
            periods.setdefault(key, {})[label] = row
    compared = []
    for key in sorted(periods):
        kind, _, subject = key.partition(":")
        then, now = periods[key].get("before", {}), periods[key].get("after", {})
        side: dict[str, Any] = {"kind": kind, "subject": subject}
        side["executions_before"] = then.get("executions", 0)
        side["executions_after"] = now.get("executions", 0)
        for field in CHANGED:
            old, new = then.get(field), now.get(field)
            side[f"{field}_before"], side[f"{field}_after"] = old, new
            side[f"{field}_change"] = (
                round((new - old) / old, 4) if old not in (None, 0) and new is not None else None
            )
        compared.append(side)
    return compared


async def workspaces(session: AsyncSession) -> list[dict[str, Any]]:
    found = await session.execute(
        text(
            "SELECT w.id, w.name, COALESCE(p.plan, 'free') AS plan, p.at AS plan_since,"
            " w.created_at FROM workspaces w"
            " LEFT JOIN LATERAL (SELECT plan, at FROM workspace_plans wp"
            " WHERE wp.workspace_id = w.id ORDER BY at DESC, created_at DESC LIMIT 1) p ON true"
            " ORDER BY w.created_at"
        )
    )
    return _rows(found)


# ── every call, for the LEKA team (LEKA-530) ────────────────────────────────

CALLS = (
    "SELECT c.at, c.workspace_id, w.name AS workspace, u.email AS user_email, c.user_id,"
    " CASE WHEN c.purpose LIKE 'agent:%' THEN split_part(c.purpose, ':', 2) END AS agent,"
    " c.purpose AS operation, c.provider, c.model, c.version, c.route, c.owner, c.status,"
    " c.attempt, c.error, c.tokens_in, c.tokens_out, c.tokens_cached, c.tokens_thinking,"
    " c.tokens_in + c.tokens_out AS tokens_total, c.cost_usd, c.usage_reported,"
    " r.since AS rate_since, r.per_million_in, r.per_million_out, r.per_million_cached,"
    " c.latency_ms, c.run_id, c.ref"
    " FROM model_calls c JOIN workspaces w ON w.id = c.workspace_id"
    " LEFT JOIN users u ON u.id = c.user_id"
    " LEFT JOIN model_rates r ON r.id = c.rate_id"
    " WHERE c.at >= :start AND c.at < :end"
    " AND (CAST(:workspace AS uuid) IS NULL OR c.workspace_id = :workspace)"
    " AND (CAST(:user_id AS uuid) IS NULL OR c.user_id = :user_id)"
    " AND (CAST(:email AS text) IS NULL OR lower(u.email) = lower(:email))"
    " AND (CAST(:agent AS text) IS NULL OR c.purpose = 'agent:' || :agent"
    " OR c.purpose LIKE 'agent:' || :agent || ':%')"
    " AND (CAST(:provider AS text) IS NULL OR c.provider = :provider)"
    " AND (CAST(:model AS text) IS NULL OR c.model = :model)"
    " AND (CAST(:operation AS text) IS NULL OR c.purpose = :operation"
    " OR c.purpose LIKE :operation || ':%' OR c.purpose LIKE :operation || '.%')"
    " AND (CAST(:status AS text) IS NULL OR c.status = :status)"
    " ORDER BY c.at DESC, c.id"
)
# What a call can be summed by.
BY = {
    "workspace": ("workspace_id", "workspace"),
    "user": ("user_id", "user_email"),
    "agent": ("agent",),
    "model": ("provider", "model"),
    "operation": ("operation",),
    "day": ("day",),
}
SUMMED = ("tokens_in", "tokens_out", "tokens_cached", "tokens_total")


def _basis(row: dict[str, Any]) -> str:
    """How a call's cost was reached, said."""
    if row["owner"] == "workspace":
        return "the workspace's own model: its account, not LEKA's"
    if row["cost_usd"] is None:
        return "not known: no rate for this model at the time, or no usage said"
    if row["rate_since"] is None:
        return "list price"
    said = (
        f"rate from {row['rate_since']}: {row['per_million_in']:g} in,"
        f" {row['per_million_out']:g} out per million tokens"
    )
    if row["per_million_cached"] is not None:
        said += f", {row['per_million_cached']:g} cached"
    return said


def _credits(row: dict[str, Any]) -> float | None:
    """The AI credits a call used: LEKA's models that answered, at its cost."""
    if row["owner"] != "leka" or row["status"] == "failed":
        return 0.0
    if row["cost_usd"] is None:
        return None
    return round(float(row["cost_usd"]) / settings.credit_usd, 4)


async def usage(
    session: AsyncSession,
    *,
    start: date,
    end: date,
    workspace: uuid.UUID | None = None,
    user: str | None = None,
    agent: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    operation: str | None = None,
    status: str | None = None,
    by: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Every call in [start, end) that matches, the latest first — or summed
    `by` workspace, user, agent, model, operation or day. `user`: an id or
    an e-mail address. Costs in US dollars, LEKA's; the basis said."""
    person: uuid.UUID | None = None
    email: str | None = None
    if user:
        try:
            person = uuid.UUID(user)
        except ValueError:
            email = user
    found = await session.execute(
        text(CALLS if by else f"{CALLS} LIMIT :limit"),
        {
            "start": start,
            "end": end,
            "workspace": workspace,
            "user_id": person,
            "email": email,
            "agent": agent,
            "provider": provider,
            "model": model,
            "operation": operation,
            "status": status,
            "limit": limit,
        },
    )
    rows = _rows(found)
    for row in rows:
        row["currency"] = "USD"
        row["cost_basis"] = _basis(row)
        row["credits_used"] = _credits(row)
        row["day"] = str(row["at"])[:10]
    if not by:
        return rows
    keys = BY[by]
    summed: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        into = summed.setdefault(
            key,
            {
                **{k: row[k] for k in keys},
                "calls": 0,
                "failed": 0,
                **dict.fromkeys(SUMMED, 0),
                "cost_usd": 0.0,
                "cost_not_known": 0,
                "credits_used": 0.0,
                "currency": "USD",
                "first_at": row["at"],
                "last_at": row["at"],
            },
        )
        into["calls"] += 1
        into["failed"] += row["status"] != "ok"
        for field in SUMMED:
            into[field] += row[field]
        if row["cost_usd"] is None:
            into["cost_not_known"] += 1
        else:
            into["cost_usd"] = round(into["cost_usd"] + row["cost_usd"], 6)
        if row["credits_used"] is not None:
            into["credits_used"] = round(into["credits_used"] + row["credits_used"], 4)
        into["first_at"] = min(into["first_at"], row["at"])
        into["last_at"] = max(into["last_at"], row["at"])
    return sorted(summed.values(), key=lambda r: -r["cost_usd"])


def columns(rows: Sequence[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows:
        seen.update(dict.fromkeys(row))
    return list(seen)
