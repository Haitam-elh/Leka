"""What a workspace asked of language models (LEKA-394, 429): how many calls,
how many failed, the tokens — those read from the provider's cache apart —
what they cost at list price, how long they took — by day, by model, by
purpose; LEKA's model and the workspace's own apart; and what one intention
costs, measured: every call made for it, understanding and answer, summed
per intention, averaged. Read from model_calls: what was recorded, nothing
estimated twice.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.models import LLMRun, ModelCall


@dataclass
class Tally:
    calls: int = 0
    failed: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    cost_usd: float = 0.0
    # Calls whose cost is not known (a model without a published price).
    unpriced: int = 0
    latency_ms: int = 0

    def add(self, call: ModelCall) -> None:
        self.calls += 1
        if call.status != "ok":
            self.failed += 1
        self.tokens_in += call.tokens_in
        self.tokens_out += call.tokens_out
        self.tokens_cached += call.tokens_cached
        if call.cost_usd is None:
            if call.status == "ok":
                self.unpriced += 1
        else:
            self.cost_usd += call.cost_usd
        self.latency_ms += call.latency_ms


@dataclass
class ModelUsage:
    days: int
    total: Tally = field(default_factory=Tally)
    previous: Tally = field(default_factory=Tally)
    by_owner: dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))
    by_day: dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))
    by_model: dict[tuple[str, str], Tally] = field(default_factory=lambda: defaultdict(Tally))
    by_purpose: dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))
    fallbacks: int = 0
    latest: list[ModelCall] = field(default_factory=list)
    # The work the LLM runtime had models do (LEKA-429), by how it ended,
    # and the latest.
    runs: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latest_runs: list[LLMRun] = field(default_factory=list)
    # What each intention of the period cost, every call made for it.
    intentions: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    @property
    def per_intention(self) -> float | None:
        """What one intention costs, on average — none before the first."""
        if not self.intentions:
            return None
        return sum(self.intentions.values()) / len(self.intentions)


async def model_calls(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    limit: int = 100,
) -> Sequence[ModelCall]:
    """The latest calls, for audit (LEKA-406): for one person, one run."""
    query = (
        select(ModelCall)
        .where(ModelCall.workspace_id == workspace_id)
        .order_by(ModelCall.at.desc(), ModelCall.id)
        .limit(limit)
    )
    if user_id is not None:
        query = query.where(ModelCall.user_id == user_id)
    if run_id is not None:
        query = query.where(ModelCall.run_id == run_id)
    return (await session.scalars(query)).all()


async def model_usage(
    session: AsyncSession, workspace_id: uuid.UUID, *, now: datetime, days: int = 30
) -> ModelUsage:
    since = now - timedelta(days=days)
    before = since - timedelta(days=days)
    rows = (
        await session.scalars(
            select(ModelCall)
            .where(ModelCall.workspace_id == workspace_id, ModelCall.at >= before)
            .order_by(ModelCall.at.desc())
        )
    ).all()
    usage = ModelUsage(days=days)
    for call in rows:
        if call.at < since:
            usage.previous.add(call)
            continue
        usage.total.add(call)
        usage.by_owner[call.owner].add(call)
        usage.by_day[call.at.date().isoformat()].add(call)
        usage.by_model[(call.provider, call.model)].add(call)
        usage.by_purpose[call.purpose].add(call)
        if call.ref and call.ref.startswith("intention:") and call.cost_usd is not None:
            usage.intentions[call.ref] += call.cost_usd
        if call.route not in ("own", "default") and call.status == "ok":
            usage.fallbacks += 1
        if len(usage.latest) < 20:
            usage.latest.append(call)
    runs = (
        await session.scalars(
            select(LLMRun)
            .where(LLMRun.workspace_id == workspace_id, LLMRun.started_at >= since)
            .order_by(LLMRun.started_at.desc())
        )
    ).all()
    for run in runs:
        usage.runs[run.status] += 1
    usage.latest_runs = list(runs[:10])
    return usage
