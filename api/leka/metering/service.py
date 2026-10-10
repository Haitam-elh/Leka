"""The usage ledger, derived (LEKA-430): each execution's calls read again
and summed — what it took, what it cost LEKA — and its row written again
whole. docs/metering.md says how, and why.

    meter()            these executions of a workspace, metered now
    sweep()            every execution a call was made for, or a run ended,
                       since then — the schedule's every quarter of an hour,
                       a backfill's since the first call
    intention_cost()   what an intention cost, end to end, by step

What a call says is read as it was kept. A call that failed was not
answered: counted, never priced (providers do not bill it). One answered
whose provider did not say what it used has no tokens and no cost — the
execution's are then partial, or unknown, never short and said measured.
A call kept before LEKA-430 asked (usage_reported none) is taken as said
when it has tokens.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import AgentRun, LLMRun, ModelCall, WorkflowRun
from leka.db import session_factory, system_scope
from leka.intentions import Intention
from leka.metering.repository import MeteringRepository, split
from leka.metering.schemas import CostStatus, ExecutionCost, IntentionCost, StepCost, TokensStatus

logger = structlog.get_logger(__name__)

# What the schedule reads again each time: a run's calls arrive over
# minutes, an agent's over its whole run.
WINDOW = timedelta(hours=6)
# Executions metered in one transaction, at most.
BATCH = 200

LEKA_DOES_NOT_MEASURE = {
    # Context is retrieved in the database: no embedding model is paid.
    "embedding_cost": "not_applicable",
    "tool_cost": "unavailable",
    "infra_cost": "unavailable",
}


def _said(call: ModelCall) -> bool:
    """Whether the provider said what an answered call used."""
    if call.usage_reported is not None:
        return call.usage_reported
    return call.tokens_in + call.tokens_out > 0


def tokens_status(answered: int, said: int) -> TokensStatus:
    if not answered:
        return "none"
    if said == answered:
        return "measured"
    return "partial" if said else "unknown"


def cost_status(answered: int, priced: int) -> CostStatus:
    if not answered:
        return "none"
    if priced == answered:
        return "estimated"
    return "partial" if priced else "unknown"


def _sum(values: Sequence[float]) -> float | None:
    return round(sum(values), 6) if values else None


def steps_of(calls: Sequence[ModelCall]) -> dict[str, StepCost]:
    steps: dict[str, StepCost] = {}
    for call in calls:
        step = steps.setdefault(call.purpose, StepCost())
        step.calls += 1
        retried = call.attempt > 1
        step.retries += int(retried)
        if call.status == "failed":
            step.failed += 1
            continue
        step.invalid += int(call.status == "invalid")
        if _said(call):
            step.tokens_in += call.tokens_in
            step.tokens_out += call.tokens_out
        if call.cost_usd is None:
            step.unpriced += 1
            continue
        step.cost_usd = round(step.cost_usd + call.cost_usd, 6)
        if call.status == "invalid":
            step.invalid_cost_usd = round(step.invalid_cost_usd + call.cost_usd, 6)
        if retried:
            step.retry_cost_usd = round(step.retry_cost_usd + call.cost_usd, 6)
    return steps


def measured(calls: Sequence[ModelCall]) -> dict[str, Any]:
    """What these calls took and cost, said as far as it is known."""
    answered = [c for c in calls if c.status != "failed"]
    said = [c for c in answered if _said(c)]
    priced = [c for c in answered if c.cost_usd is not None]

    def tokens(field: str) -> int | None:
        return sum(getattr(c, field) for c in said) if said else None

    return {
        "calls": len(calls),
        "failed_calls": len(calls) - len(answered),
        "invalid_calls": sum(c.status == "invalid" for c in calls),
        "retries": sum(c.attempt > 1 for c in calls),
        "fallbacks": sum(c.route not in ("own", "default") for c in calls),
        "tool_calls": sum(c.tool_calls for c in calls),
        "unreported_calls": len(answered) - len(said),
        "latency_ms": sum(c.latency_ms for c in calls),
        "tokens_in": tokens("tokens_in"),
        "tokens_out": tokens("tokens_out"),
        "tokens_thinking": tokens("tokens_thinking"),
        "tokens_cached": tokens("tokens_cached"),
        "tokens_status": tokens_status(len(answered), len(said)),
        "llm_cost_usd": _sum([c.cost_usd for c in priced if c.cost_usd is not None]),
        "leka_cost_usd": _sum(
            [c.cost_usd for c in priced if c.cost_usd is not None and c.owner == "leka"]
        ),
        "workspace_cost_usd": _sum(
            [c.cost_usd for c in priced if c.cost_usd is not None and c.owner == "workspace"]
        ),
        "cost_status": cost_status(len(answered), len(priced)),
        "models": sorted({f"{c.provider}/{c.model}" for c in answered}),
        "rates": sorted({str(c.rate_id) for c in calls if c.rate_id is not None}),
        "steps": {k: v.model_dump() for k, v in steps_of(calls).items()},
    }


class Metering:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = MeteringRepository(session)

    async def meter(
        self, workspace_id: uuid.UUID, executions: Collection[str], *, now: datetime
    ) -> int:
        """These executions' rows, written again from what was kept — one
        whose run and calls are gone (a workspace's data forgotten) is left
        as it was. How many were written."""
        calls = await self._repository.calls(workspace_id, executions)
        ids: dict[str, set[uuid.UUID]] = {}
        for execution in executions:
            kind, rest = split(execution)
            try:
                ids.setdefault(kind, set()).add(uuid.UUID(rest))
            except ValueError:
                continue
        agents = await self._repository.agent_runs(workspace_id, ids.get("agent_run", ()))
        workflows = await self._repository.workflow_runs(workspace_id, ids.get("workflow_run", ()))
        runs = await self._repository.llm_runs(workspace_id, ids.get("llm_run", ()))
        read = await self._repository.read_by(workspace_id, ids.get("llm_run", set()))
        intentions = await self._repository.intentions(workspace_id, ids.get("intention", ()))
        rows = []
        for execution in sorted(executions):
            said = _execution(
                execution,
                calls.get(execution, []),
                agents=agents,
                workflows=workflows,
                runs=runs,
                read=read,
                intentions=intentions,
            )
            if said is None:
                continue
            rows.append(
                {
                    "workspace_id": workspace_id,
                    "execution": execution,
                    **said,
                    **measured(calls.get(execution, [])),
                    **LEKA_DOES_NOT_MEASURE,
                    "metered_at": now,
                    "updated_at": now,
                }
            )
        await self._repository.write(rows)
        return len(rows)

    async def intention_cost(
        self, workspace_id: uuid.UUID, intention_id: uuid.UUID, *, now: datetime
    ) -> IntentionCost:
        """Its executions metered again, then summed."""
        executions = await self._repository.of_intention(workspace_id, intention_id)
        await self.meter(workspace_id, executions, now=now)
        records = await self._repository.records(workspace_id, intention_id=intention_id)
        steps: dict[str, StepCost] = {}
        for record in records:
            for purpose, raw in record.steps.items():
                step = StepCost.model_validate(raw)
                total = steps.setdefault(purpose, StepCost())
                for field, value in step.model_dump().items():
                    setattr(total, field, round(getattr(total, field) + value, 6))
        answered = sum(r.calls - r.failed_calls for r in records)
        said = sum(r.calls - r.failed_calls - r.unreported_calls for r in records)
        unpriced = sum(s.unpriced for s in steps.values())

        def known(values: Sequence[float | int | None]) -> Any:
            present = [v for v in values if v is not None]
            return round(sum(present), 6) if present else None

        return IntentionCost(
            intention_id=intention_id,
            executions=[
                ExecutionCost(
                    execution=r.execution,
                    kind=r.kind,
                    subject=r.subject,
                    subject_version=r.subject_version,
                    outcome=r.outcome,
                    started_at=r.started_at,
                    duration_ms=r.duration_ms,
                    calls=r.calls,
                    retries=r.retries,
                    tokens_in=r.tokens_in,
                    tokens_out=r.tokens_out,
                    tokens_status=r.tokens_status,
                    llm_cost_usd=r.llm_cost_usd,
                    cost_status=r.cost_status,
                )
                for r in records
            ],
            calls=sum(r.calls for r in records),
            retries=sum(r.retries for r in records),
            tokens_in=known([r.tokens_in for r in records]),
            tokens_out=known([r.tokens_out for r in records]),
            tokens_status=tokens_status(answered, said),
            llm_cost_usd=known([r.llm_cost_usd for r in records]),
            leka_cost_usd=known([r.leka_cost_usd for r in records]),
            workspace_cost_usd=known([r.workspace_cost_usd for r in records]),
            cost_status=cost_status(answered, answered - unpriced),
            steps=steps,
        )


def _execution(
    execution: str,
    calls: Sequence[ModelCall],
    *,
    agents: Mapping[uuid.UUID, AgentRun],
    workflows: Mapping[uuid.UUID, WorkflowRun],
    runs: Mapping[uuid.UUID, LLMRun],
    read: Mapping[uuid.UUID, uuid.UUID],
    intentions: Mapping[uuid.UUID, Intention],
) -> dict[str, Any] | None:
    """What an execution was — its subject, for whom, how it ended, when —
    from its run; from its calls alone when it has none. None when neither
    is left."""
    kind, rest = split(execution)
    first = calls[0].at if calls else None
    last = calls[-1].at if calls else None
    caller = next((c.user_id for c in calls if c.user_id is not None), None)
    answered = any(c.status != "failed" for c in calls)
    said: dict[str, Any] = {
        "kind": kind,
        "intention_id": None,
        "subject": calls[0].purpose[:100] if calls else kind,
        "subject_version": None,
        "user_id": caller,
        "outcome": "ok" if answered else "failed",
        "started_at": first,
        "ended_at": last,
    }
    run: AgentRun | WorkflowRun | None = None
    if kind == "agent_run":
        run = agents.get(uuid.UUID(rest))
    elif kind == "workflow_run":
        run = workflows.get(uuid.UUID(rest))
    if run is not None:
        said |= {
            "intention_id": run.intention_id,
            "subject": run.key,
            "subject_version": run.version,
            "user_id": run.requested_by or caller,
            "outcome": run.status,
            "started_at": run.started_at or run.queued_at,
            "ended_at": run.finished_at,
        }
    elif kind == "llm_run" and (llm := runs.get(uuid.UUID(rest))) is not None:
        ref = llm.ref or ""
        intention = (
            uuid.UUID(ref.removeprefix("intention:"))
            if ref.startswith("intention:") and _is_uuid(ref.removeprefix("intention:"))
            else read.get(llm.id)
        )
        said |= {
            "intention_id": intention,
            "subject": llm.purpose,
            "outcome": llm.status,
            "started_at": llm.started_at,
            "ended_at": llm.finished_at,
        }
    elif kind == "intention":
        ident = uuid.UUID(rest)
        found = intentions.get(ident)
        said |= {"intention_id": ident, "subject": "intention"}
        if found is not None:
            said |= {"user_id": found.created_by or caller}
    elif kind == "work":
        said["subject"] = rest.rpartition(":")[0][:100]
    if said["started_at"] is None:
        return None
    ended = said["ended_at"]
    said["duration_ms"] = (
        int((ended - said["started_at"]).total_seconds() * 1000) if ended is not None else None
    )
    return said


def _is_uuid(text: str) -> bool:
    try:
        uuid.UUID(text)
    except ValueError:
        return False
    return True


# ── the schedule, a backfill ────────────────────────────────────────────────


def run_metering_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(sweep())


async def sweep(*, since: datetime | None = None, now: datetime | None = None) -> dict[str, int]:
    """Every execution a call was made for, or a run ended, since `since`
    (the last WINDOW) — metered again, a workspace at a time, BATCH at a
    time. One that fails is logged; the others are metered all the same.
    Idempotent: run again, the same rows."""
    moment = now or datetime.now(UTC)
    start = since or moment - WINDOW
    with system_scope():
        async with session_factory() as session:
            touched = await MeteringRepository(session).touched(start)
    metered: dict[str, int] = {}
    for workspace_id, executions in touched.items():
        ordered = sorted(executions)
        count = 0
        try:
            for at in range(0, len(ordered), BATCH):
                with system_scope():
                    async with session_factory() as session:
                        count += await Metering(session).meter(
                            workspace_id, ordered[at : at + BATCH], now=moment
                        )
                        await session.commit()
        except Exception:
            logger.exception("metering_failed", workspace=str(workspace_id))
        metered[str(workspace_id)] = count
    logger.info("metering_swept", workspaces=len(metered), executions=sum(metered.values()))
    return metered
