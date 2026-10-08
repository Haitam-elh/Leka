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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.intentions.models import IntentionAnalysis

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
