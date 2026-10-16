"""How much LEKA's capabilities are used (LEKA-393): what its analyses ran
(LEKA-388, `intention_analyses.steps`) — each capability's runs this week and
the week before, its failures, how long it took — and how long an analysis
takes, for the catalogue (mockup 13).

Read from what each analysis kept of its steps: a capability skipped or not
called did not run, and is not counted.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import Source, SourceStatus
from leka.intentions.models import Intention, IntentionAnalysis, IntentionPlan
from leka.knowledge import Entity
from leka.platform import Membership

# As the home and Sources count them (web/lib/sources.ts isConnected): one in
# error is still connected — its failure is said beside it, not hidden by the count.
CONNECTED = (SourceStatus.ACTIVE, SourceStatus.DEGRADED, SourceStatus.ERROR)

# A step that ran: it succeeded, or it did not.
RAN = frozenset({"succeeded", "failed", "timed_out"})
FAILED = frozenset({"failed", "timed_out"})
WEEK = timedelta(days=7)


@dataclass
class Use:
    runs: int = 0
    previous: int = 0
    failures: int = 0
    total_ms: int = 0
    # This week's runs, by day (YYYY-MM-DD).
    days: Counter[str] = field(default_factory=Counter)

    @property
    def average_ms(self) -> int | None:
        return round(self.total_ms / self.runs) if self.runs else None


@dataclass
class Usage:
    by_key: dict[str, Use]
    days: list[str]  # this week's, oldest first
    analysis_ms: int | None  # an analysis this week, on average
    analysis_previous_ms: int | None

    def of(self, key: str) -> Use:
        return self.by_key.get(key, Use())


def _mean(values: list[float]) -> int | None:
    return round(sum(values) / len(values)) if values else None


async def capability_usage(
    session: AsyncSession, workspace_id: uuid.UUID, *, now: datetime
) -> Usage:
    """This week's and the week before's, as the analyses kept them."""
    since = now - 2 * WEEK
    start = now - WEEK
    rows = await session.execute(
        select(
            IntentionAnalysis.started_at, IntentionAnalysis.finished_at, IntentionAnalysis.steps
        ).where(
            IntentionAnalysis.workspace_id == workspace_id,
            IntentionAnalysis.started_at >= since,
            IntentionAnalysis.started_at <= now,
        )
    )
    by_key: dict[str, Use] = defaultdict(Use)
    durations: dict[bool, list[float]] = {True: [], False: []}
    for started, finished, steps in rows.tuples():
        current = started >= start
        if finished is not None:
            durations[current].append((finished - started).total_seconds() * 1000)
        for step in steps or []:
            if not isinstance(step, dict) or step.get("status") not in RAN:
                continue
            use = by_key[str(step.get("name"))]
            if current:
                use.runs += 1
                spent = step.get("duration_ms")
                use.total_ms += spent if isinstance(spent, int) else 0
                use.days[started.date().isoformat()] += 1
                if step.get("status") in FAILED:
                    use.failures += 1
            else:
                use.previous += 1
    days = [(start + timedelta(days=n + 1)).date().isoformat() for n in range(7)]
    return Usage(dict(by_key), days, _mean(durations[True]), _mean(durations[False]))


# ── the workspace's consumption (Facturation) ───────────────────────────────


class WorkspaceUsageRead(BaseModel):
    """What the workspace holds and did this month — Facturation's figures,
    every one counted, none estimated."""

    model_config = ConfigDict(frozen=True)

    month_start: datetime
    members: int
    sources: int
    sources_connected: int
    entities: int
    intentions: int = Field(description="Asked this month")
    analyses: int = Field(description="Run this month")
    capability_runs: int = Field(description="Capabilities run this month, by the analyses")
    plans: int = Field(description="Plans of action run this month")
    previous: dict[str, int] = Field(description="Last month: intentions, analyses, runs")


async def workspace_usage(
    session: AsyncSession, workspace_id: uuid.UUID, *, now: datetime
) -> WorkspaceUsageRead:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    before = (start - timedelta(days=1)).replace(day=1)

    async def count(statement: Select[tuple[int]]) -> int:
        return int(await session.scalar(statement) or 0)

    analyses = select(IntentionAnalysis.started_at, IntentionAnalysis.steps).where(
        IntentionAnalysis.workspace_id == workspace_id,
        IntentionAnalysis.started_at >= before,
    )
    runs: Counter[str] = Counter()
    ran: Counter[str] = Counter()
    for started, steps in (await session.execute(analyses)).tuples():
        month = "now" if started >= start else "before"
        ran[month] += 1
        runs[month] += sum(1 for s in steps or [] if isinstance(s, dict) and s.get("status") in RAN)
    intentions_now = await count(
        select(func.count()).where(
            Intention.workspace_id == workspace_id, Intention.created_at >= start
        )
    )
    intentions_before = await count(
        select(func.count()).where(
            Intention.workspace_id == workspace_id,
            Intention.created_at >= before,
            Intention.created_at < start,
        )
    )
    return WorkspaceUsageRead(
        month_start=start,
        members=await count(select(func.count()).where(Membership.workspace_id == workspace_id)),
        sources=await count(select(func.count()).where(Source.workspace_id == workspace_id)),
        sources_connected=await count(
            select(func.count()).where(
                Source.workspace_id == workspace_id, Source.status.in_(CONNECTED)
            )
        ),
        entities=await count(
            select(func.count()).where(
                Entity.workspace_id == workspace_id, Entity.lifecycle != "removed"
            )
        ),
        intentions=intentions_now,
        analyses=ran["now"],
        capability_runs=runs["now"],
        plans=await count(
            select(func.count()).where(
                IntentionPlan.workspace_id == workspace_id,
                IntentionPlan.started_at.is_not(None),
                IntentionPlan.started_at >= start,
            )
        ),
        previous={
            "intentions": intentions_before,
            "analyses": ran["before"],
            "capability_runs": runs["before"],
        },
    )
