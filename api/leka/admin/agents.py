"""Every agent of LEKA, and how it is used (LEKA-552): adopted by how many
organisations, run how often, how well, how fast, what its runs used and
cost at the providers' rates, what it brings in when it is sold alone —
each agent on its own, ranked, filtered, and set beside the period before.

Read where each is kept, never copied, inside `system_scope()` like every
admin read (leka/admin/reads.py):

- the agents: the capability catalogue (agents/registry.yaml and each
  agent's SKILL.md), so an agent that never ran is listed too, and one
  taken out of the registry still says what it did;
- what they did: `agent_runs`, one row per run;
- what their runs used and cost: the metering ledger (`usage_records`,
  one line per run), priced at the rates in force (`model_rates`). A run
  whose calls are not all priced leaves the cost partial, said so, never
  counted as 0;
- what they bring in: the options bought (`agent_entitlements`) and their
  recurring price as Stripe said it (LEKA-548). Only an agent bought alone
  has a revenue of its own: a bundle's is never split among its agents.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import String, cast, distinct, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.overview import AdminWindow, buckets
from leka.admin.reads import _credits, _like, _organisation_names
from leka.admin.schemas import (
    AgentBundle,
    AgentFailure,
    AgentModelUse,
    AgentOffer,
    AgentOrganisationUse,
    AgentPoint,
    AgentPrevious,
    AgentRecord,
    AgentStat,
    AgentVersionUse,
    CostStatus,
    OrganisationRef,
)
from leka.billing import AgentEntitlement, monthly
from leka.billing import catalogue as offer_catalogue
from leka.capabilities import AgentRun, Definition, Kind, catalogue
from leka.metering import UsageRecord
from leka.platform import Workspace

AgentSort = Literal[
    "runs", "organisations", "success_rate", "cost", "duration", "revenue", "last_run"
]
TOP = 20
CURRENCY = "eur"
# Every call of the run priced, or no call to price.
PRICED = ("estimated", "none")


@dataclass(frozen=True)
class AgentFilters:
    since: datetime | None = None
    until: datetime | None = None
    organisation_id: uuid.UUID | None = None
    organisation: str | None = None
    user_id: uuid.UUID | None = None
    agent: str | None = None
    model: str | None = None
    status: str | None = None


def registry() -> dict[str, Definition]:
    """The registry's agents, by key: the catalogue's, workflows and LEKA's
    own capabilities left out."""
    return {d.key: d for d in catalogue() if d.kind is Kind.AGENT}


def _where(f: AgentFilters) -> list[Any]:
    where: list[Any] = []
    if f.since:
        where.append(AgentRun.queued_at >= f.since)
    if f.until:
        where.append(AgentRun.queued_at < f.until)
    if f.organisation_id:
        where.append(AgentRun.workspace_id == f.organisation_id)
    if f.organisation and f.organisation.strip():
        pattern = _like(f.organisation)
        where.append(
            AgentRun.workspace_id.in_(
                select(Workspace.id).where(
                    or_(Workspace.name.ilike(pattern), Workspace.slug.ilike(pattern))
                )
            )
        )
    if f.user_id:
        where.append(AgentRun.requested_by == f.user_id)
    if f.agent:
        where.append(AgentRun.key == f.agent)
    if f.model:
        where.append(AgentRun.model == f.model)
    if f.status:
        where.append(AgentRun.status == f.status)
    return where


def _metered() -> Any:
    """A run and its line of the metering ledger, when it has one."""
    return (
        select()
        .select_from(AgentRun)
        .outerjoin(
            UsageRecord,
            (UsageRecord.workspace_id == AgentRun.workspace_id)
            & (UsageRecord.execution == literal("agent_run:") + cast(AgentRun.id, String)),
        )
    )


def _figures() -> list[Any]:
    """What every group of runs says, in this order."""
    ended = AgentRun.finished_at.is_not(None) & AgentRun.started_at.is_not(None)
    duration = func.extract("epoch", AgentRun.finished_at - AgentRun.started_at) * 1000
    unpriced = or_(UsageRecord.id.is_(None), UsageRecord.cost_status.not_in(PRICED))
    return [
        func.count(),
        func.count(distinct(AgentRun.workspace_id)),
        func.count().filter(AgentRun.status == "succeeded"),
        func.count().filter(AgentRun.status == "failed"),
        func.count().filter(AgentRun.status == "cancelled"),
        func.avg(duration).filter(ended),
        func.max(AgentRun.queued_at),
        func.sum(UsageRecord.calls),
        func.sum(UsageRecord.tokens_in),
        func.sum(UsageRecord.tokens_out),
        func.sum(UsageRecord.llm_cost_usd),
        func.sum(UsageRecord.leka_cost_usd),
        func.count().filter(unpriced),
    ]


@dataclass(frozen=True)
class _Figures:
    runs: int = 0
    organisations: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    average_ms: float | None = None
    last: datetime | None = None
    calls: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None
    leka_cost: float | None = None
    unpriced: int = 0

    @property
    def success_rate(self) -> float | None:
        ended = self.succeeded + self.failed
        return round(self.succeeded / ended, 4) if ended else None

    @property
    def cost_status(self) -> CostStatus:
        if self.runs == 0:
            return "none"
        if self.unpriced == 0:
            return "measured"
        return "unavailable" if self.unpriced == self.runs else "partial"

    @property
    def cost_usd(self) -> float | None:
        """Of the runs priced: none priced, unknown; priced with no call, 0."""
        if self.cost_status in ("unavailable", "none"):
            return None
        return round(self.cost or 0.0, 6)


def _read(row: Sequence[Any]) -> _Figures:
    (runs, organisations, succeeded, failed, cancelled, average, last) = row[:7]
    (calls, tokens_in, tokens_out, cost, leka_cost, unpriced) = row[7:]
    return _Figures(
        runs=int(runs),
        organisations=int(organisations),
        succeeded=int(succeeded),
        failed=int(failed),
        cancelled=int(cancelled),
        average_ms=float(average) if average is not None else None,
        last=last,
        calls=int(calls) if calls is not None else None,
        tokens_in=int(tokens_in) if tokens_in is not None else None,
        tokens_out=int(tokens_out) if tokens_out is not None else None,
        cost=float(cost) if cost is not None else None,
        leka_cost=float(leka_cost) if leka_cost is not None else None,
        unpriced=int(unpriced),
    )


async def _by_agent(session: AsyncSession, f: AgentFilters) -> dict[str, _Figures]:
    rows = await session.execute(
        _metered().add_columns(AgentRun.key, *_figures()).where(*_where(f)).group_by(AgentRun.key)
    )
    return {row[0]: _read(row[1:]) for row in rows.all()}


@dataclass
class _Revenue:
    cents: float = 0.0
    purchases: int = 0
    unknown: int = 0
    bundles: int = 0

    @property
    def eur(self) -> float | None:
        if self.purchases == 0 or self.unknown:
            return None
        return round(self.cents / 100, 2)


async def _revenues(
    session: AsyncSession, f: AgentFilters, *, now: datetime
) -> dict[str, _Revenue]:
    """What each agent bought alone brings in a month now, and how many
    bundles bought include it, in the organisations asked."""
    statement = select(
        AgentEntitlement.kind, AgentEntitlement.key, AgentEntitlement.recurring
    ).where(
        AgentEntitlement.origin == "purchase",
        AgentEntitlement.status == "active",
        AgentEntitlement.kind.in_(("agent", "bundle")),
    )
    if f.organisation_id:
        statement = statement.where(AgentEntitlement.workspace_id == f.organisation_id)
    if f.organisation and f.organisation.strip():
        pattern = _like(f.organisation)
        statement = statement.where(
            AgentEntitlement.workspace_id.in_(
                select(Workspace.id).where(
                    or_(Workspace.name.ilike(pattern), Workspace.slug.ilike(pattern))
                )
            )
        )
    add_ons = offer_catalogue().add_ons
    found: dict[str, _Revenue] = defaultdict(_Revenue)
    for kind, key, recurring in (await session.execute(statement)).tuples().all():
        if kind == "bundle":
            bundle = add_ons.bundle(key)
            for agent in bundle.agents if bundle else ():
                found[agent].bundles += 1
            continue
        revenue = found[key]
        revenue.purchases += 1
        cents = monthly(recurring, now)
        if cents is None or not recurring or str(recurring.get("currency")) != CURRENCY:
            revenue.unknown += 1
        else:
            revenue.cents += cents
    return found


def _stat(
    key: str,
    figures: _Figures,
    definition: Definition | None,
    revenue: _Revenue | None,
    previous: _Figures | None,
    *,
    compared: bool,
) -> AgentStat:
    sold = revenue or _Revenue()
    return AgentStat(
        key=key,
        title=definition.title if definition else None,
        category=definition.category if definition else None,
        version=definition.version if definition else None,
        lifecycle=definition.lifecycle.value if definition else None,
        runs=figures.runs,
        organisations=figures.organisations,
        succeeded=figures.succeeded,
        failed=figures.failed,
        cancelled=figures.cancelled,
        success_rate=figures.success_rate,
        average_duration_ms=int(figures.average_ms) if figures.average_ms is not None else None,
        calls=figures.calls,
        tokens_in=figures.tokens_in,
        tokens_out=figures.tokens_out,
        cost_usd=figures.cost_usd,
        cost_status=figures.cost_status,
        unpriced_runs=figures.unpriced,
        credits=_credits(figures.leka_cost),
        revenue_eur=sold.eur,
        purchases=sold.purchases,
        bundle_purchases=sold.bundles,
        last_run_at=figures.last,
        previous=AgentPrevious(
            runs=(before := previous or _Figures()).runs,
            organisations=before.organisations,
            success_rate=before.success_rate,
            cost_usd=before.cost_usd,
        )
        if compared
        else None,
    )


SORTS: dict[AgentSort, Callable[[AgentStat], Any]] = {
    "runs": lambda s: s.runs,
    "organisations": lambda s: s.organisations,
    "success_rate": lambda s: s.success_rate,
    "cost": lambda s: s.cost_usd,
    "duration": lambda s: s.average_duration_ms,
    "revenue": lambda s: s.revenue_eur,
    "last_run": lambda s: s.last_run_at,
}


def ranked(
    stats: Sequence[AgentStat], sort: AgentSort = "runs", order: Literal["asc", "desc"] = "desc"
) -> list[AgentStat]:
    """By the figure asked, an unknown one last whichever the order; ties by key."""
    value = SORTS[sort]
    known = sorted((s for s in stats if value(s) is not None), key=lambda s: s.key)
    known.sort(key=value, reverse=order == "desc")
    return known + sorted((s for s in stats if value(s) is None), key=lambda s: s.key)


async def agent_stats(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    organisation_id: uuid.UUID | None = None,
    organisation: str | None = None,
    user_id: uuid.UUID | None = None,
    agent: str | None = None,
    model: str | None = None,
    status: str | None = None,
    lifecycle: str | None = None,
    unused: bool = False,
    compare: bool = False,
    sort: AgentSort = "runs",
    order: Literal["asc", "desc"] = "desc",
    now: datetime | None = None,
) -> list[AgentStat]:
    """One row per agent that ran, or — `unused` — per agent of the
    registry too; `compare` (a period asked): beside each, the same figures
    over the period just before, as long as it."""
    moment = now or datetime.now(UTC)
    f = AgentFilters(
        since=since,
        until=until,
        organisation_id=organisation_id,
        organisation=organisation,
        user_id=user_id,
        agent=agent,
        model=model,
        status=status,
    )
    known = registry()
    figures = await _by_agent(session, f)
    previous: dict[str, _Figures] = {}
    compared = compare and since is not None
    if compared and since is not None:
        end = until or moment
        previous = await _by_agent(session, replace(f, since=since - (end - since), until=since))
    keys = set(figures)
    if unused:
        keys |= {k for k in known if not agent or k == agent}
    if lifecycle:
        keys = {k for k in keys if k in known and known[k].lifecycle.value == lifecycle}
    revenues = await _revenues(session, f, now=moment)
    stats = [
        _stat(
            key,
            figures.get(key, _Figures()),
            known.get(key),
            revenues.get(key),
            previous.get(key),
            compared=compared,
        )
        for key in keys
    ]
    return ranked(stats, sort, order)


# ── One agent ────────────────────────────────────────────────────────────────


def _offer(key: str) -> AgentOffer:
    add_ons = offer_catalogue().add_ons
    sold = add_ons.agents.get(key)
    price = add_ons.prices.get(key)
    return AgentOffer(
        tier=str(sold.tier) if sold else None,
        monthly_price_eur=round(price / 100, 2) if price is not None else None,
        bundles=[
            AgentBundle(key=b.key, fr=b.name.fr, en=b.name.en)
            for b in add_ons.bundles
            if key in b.agents
        ],
        included_from=add_ons.included_from(key),
    )


async def agent_record(
    session: AsyncSession, key: str, window: AdminWindow, f: AgentFilters
) -> AgentRecord | None:
    """One agent over a period: None when LEKA knows no agent by this key —
    in the registry, or that ever ran."""
    known = registry()
    definition = known.get(key)
    if definition is None:
        ran = await session.scalar(select(AgentRun.id).where(AgentRun.key == key).limit(1))
        if ran is None:
            return None
    f = replace(f, agent=key, since=window.start, until=window.end)
    [stat] = await agent_stats(
        session,
        since=f.since,
        until=f.until,
        organisation_id=f.organisation_id,
        organisation=f.organisation,
        user_id=f.user_id,
        agent=key,
        model=f.model,
        status=f.status,
        unused=True,
        compare=True,
        now=window.end,
    ) or [_stat(key, _Figures(), definition, None, None, compared=True)]
    where = _where(f)

    bucket = func.date_trunc(window.bucket, AgentRun.queued_at, "UTC")
    said = {
        at.astimezone(UTC): (int(runs), int(succeeded), int(failed))
        for at, runs, succeeded, failed in (
            await session.execute(
                select(
                    bucket,
                    func.count(),
                    func.count().filter(AgentRun.status == "succeeded"),
                    func.count().filter(AgentRun.status == "failed"),
                )
                .where(*where)
                .group_by(bucket)
            )
        )
        .tuples()
        .all()
    }
    series = [
        AgentPoint(at=at, runs=r, succeeded=s, failed=x)
        for at in buckets(window)
        for r, s, x in [said.get(at, (0, 0, 0))]
    ]

    models = [
        AgentModelUse(
            model=model,
            runs=figures.runs,
            succeeded=figures.succeeded,
            failed=figures.failed,
            success_rate=figures.success_rate,
            average_duration_ms=int(figures.average_ms) if figures.average_ms is not None else None,
            cost_usd=figures.cost_usd,
        )
        for model, figures in sorted(
            (
                (row[0], _read(row[1:]))
                for row in (
                    await session.execute(
                        _metered()
                        .add_columns(AgentRun.model, *_figures())
                        .where(*where)
                        .group_by(AgentRun.model)
                    )
                ).all()
            ),
            key=lambda item: (-item[1].runs, item[0] or ""),
        )
    ]

    versions = [
        AgentVersionUse(
            version=version,
            runs=int(runs),
            success_rate=round(succeeded / (succeeded + failed), 4) if succeeded + failed else None,
            first_run_at=first,
            last_run_at=last,
        )
        for version, runs, succeeded, failed, first, last in (
            await session.execute(
                select(
                    AgentRun.version,
                    func.count(),
                    func.count().filter(AgentRun.status == "succeeded"),
                    func.count().filter(AgentRun.status == "failed"),
                    func.min(AgentRun.queued_at),
                    func.max(AgentRun.queued_at),
                )
                .where(*where)
                .group_by(AgentRun.version)
                .order_by(func.max(AgentRun.queued_at).desc())
            )
        )
        .tuples()
        .all()
    ]

    used = (
        (
            await session.execute(
                select(
                    AgentRun.workspace_id,
                    func.count(),
                    func.count().filter(AgentRun.status == "succeeded"),
                    func.count().filter(AgentRun.status == "failed"),
                    func.max(AgentRun.queued_at),
                )
                .where(*where)
                .group_by(AgentRun.workspace_id)
                .order_by(func.count().desc(), func.max(AgentRun.queued_at).desc())
                .limit(TOP)
            )
        )
        .tuples()
        .all()
    )
    names = await _organisation_names(session, (row[0] for row in used))
    organisations = [
        AgentOrganisationUse(
            organisation=OrganisationRef(id=workspace_id, name=names.get(workspace_id, "")),
            runs=int(runs),
            succeeded=int(succeeded),
            failed=int(failed),
            last_run_at=last,
        )
        for workspace_id, runs, succeeded, failed, last in used
    ]

    ended = func.max(func.coalesce(AgentRun.finished_at, AgentRun.queued_at))
    failures = [
        AgentFailure(error=error, runs=int(runs), last_at=last)
        for error, runs, last in (
            await session.execute(
                select(AgentRun.error, func.count(), ended)
                .where(*where, AgentRun.status == "failed", AgentRun.error.is_not(None))
                .group_by(AgentRun.error)
                .order_by(func.count().desc(), ended.desc())
                .limit(TOP)
            )
        )
        .tuples()
        .all()
    ]

    return AgentRecord(
        stat=stat,
        summary=definition.summary if definition else None,
        mode=definition.mode if definition else None,
        risk=definition.risk if definition else None,
        dedicated=definition.dedicated if definition else False,
        offer=_offer(key),
        bucket=window.bucket,
        series=series,
        models=models,
        versions=versions,
        organisations=organisations,
        failures=failures,
    )


__all__ = ["AgentFilters", "AgentSort", "agent_record", "agent_stats", "ranked", "registry"]
