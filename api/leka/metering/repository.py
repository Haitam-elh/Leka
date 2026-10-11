"""What the ledger reads (LEKA-430): the calls of an execution, the runs
that say what it was, the intentions they were for — and where it writes,
one row per execution, written again whole."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import AgentRun, LLMRun, ModelCall, WorkflowRun
from leka.intentions import Intention
from leka.metering.models import UsageRecord

# What a call's ref says it is about, when it is an execution of its own.
EXECUTIONS = ("agent_run", "workflow_run", "intention")


def execution_of(ref: str | None, run_id: uuid.UUID | None, purpose: str, at: datetime) -> str:
    """The execution a call was part of: what its ref says — an agent run,
    a workflow run, an intention — or the LLM runtime's run it was made in;
    else the day's work for its purpose."""
    if ref:
        kind, _, ident = ref.partition(":")
        if kind in EXECUTIONS and _uuid(ident) is not None:
            return f"{kind}:{ident}"
    if run_id is not None:
        return f"llm_run:{run_id}"
    return f"work:{purpose}:{at.date().isoformat()}"


def split(execution: str) -> tuple[str, str]:
    kind, _, rest = execution.partition(":")
    return kind, rest


def _uuid(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


class MeteringRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── what changed ────────────────────────────────────────────────────────

    async def touched(self, since: datetime) -> dict[uuid.UUID, set[str]]:
        """The executions a call was made for since then — or whose run
        ended since: its outcome changed."""
        found: dict[uuid.UUID, set[str]] = {}
        calls = await self._session.execute(
            select(
                ModelCall.workspace_id,
                ModelCall.ref,
                ModelCall.run_id,
                ModelCall.purpose,
                ModelCall.at,
            ).where(ModelCall.at >= since)
        )
        for workspace_id, ref, run_id, purpose, at in calls:
            found.setdefault(workspace_id, set()).add(execution_of(ref, run_id, purpose, at))
        for table, kind in ((AgentRun, "agent_run"), (WorkflowRun, "workflow_run")):
            ended = await self._session.execute(
                select(table.workspace_id, table.id).where(table.finished_at >= since)
            )
            for workspace_id, ident in ended:
                found.setdefault(workspace_id, set()).add(f"{kind}:{ident}")
        return found

    async def of_intention(self, workspace_id: uuid.UUID, intention_id: uuid.UUID) -> set[str]:
        """Every execution done for an intention: reading it, analysing it,
        the agents and workflows it ran."""
        found = {f"intention:{intention_id}"}
        for table, kind in ((AgentRun, "agent_run"), (WorkflowRun, "workflow_run")):
            ids = await self._session.scalars(
                select(table.id).where(
                    table.workspace_id == workspace_id, table.intention_id == intention_id
                )
            )
            found |= {f"{kind}:{ident}" for ident in ids}
        intention = await self._session.get(Intention, intention_id)
        if intention is not None and intention.workspace_id == workspace_id:
            run = _read_run(intention)
            if run is not None:
                found.add(f"llm_run:{run}")
        return found

    # ── what they were ──────────────────────────────────────────────────────

    async def calls(
        self, workspace_id: uuid.UUID, executions: Collection[str]
    ) -> dict[str, list[ModelCall]]:
        """Every call of these executions, by execution."""
        refs: set[str] = set()
        runs: set[uuid.UUID] = set()
        days: dict[str, set[str]] = {}
        for execution in executions:
            kind, rest = split(execution)
            if kind in EXECUTIONS:
                refs.add(execution)
            elif kind == "llm_run" and (run := _uuid(rest)) is not None:
                runs.add(run)
            elif kind == "work":
                purpose, _, day = rest.rpartition(":")
                days.setdefault(day, set()).add(purpose)
        which: list[Any] = []
        if refs:
            which.append(ModelCall.ref.in_(refs))
        if runs:
            which.append(ModelCall.run_id.in_(runs))
        for day, purposes in days.items():
            start = datetime.fromisoformat(day).replace(tzinfo=UTC)
            which.append(
                and_(
                    ModelCall.purpose.in_(purposes),
                    ModelCall.at >= start,
                    ModelCall.at < start + timedelta(days=1),
                )
            )
        grouped: dict[str, list[ModelCall]] = {e: [] for e in executions}
        if not which:
            return grouped
        rows = await self._session.scalars(
            select(ModelCall)
            .where(ModelCall.workspace_id == workspace_id, or_(*which))
            .order_by(ModelCall.at, ModelCall.attempt)
        )
        for call in rows:
            execution = execution_of(call.ref, call.run_id, call.purpose, call.at)
            if execution in grouped:
                grouped[execution].append(call)
        return grouped

    async def agent_runs(
        self, workspace_id: uuid.UUID, ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, AgentRun]:
        return {r.id: r for r in await self._by_ids(AgentRun, workspace_id, ids)}

    async def workflow_runs(
        self, workspace_id: uuid.UUID, ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, WorkflowRun]:
        return {r.id: r for r in await self._by_ids(WorkflowRun, workspace_id, ids)}

    async def llm_runs(
        self, workspace_id: uuid.UUID, ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, LLMRun]:
        return {r.id: r for r in await self._by_ids(LLMRun, workspace_id, ids)}

    async def intentions(
        self, workspace_id: uuid.UUID, ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, Intention]:
        return {r.id: r for r in await self._by_ids(Intention, workspace_id, ids)}

    async def read_by(
        self, workspace_id: uuid.UUID, runs: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, uuid.UUID]:
        """The intention each of these LLM runs read, by run."""
        if not runs:
            return {}
        path = Intention.understanding["read_by"]["run_id"].astext
        rows = await self._session.execute(
            select(Intention.id, path).where(
                Intention.workspace_id == workspace_id,
                path.in_([str(r) for r in runs]),
            )
        )
        return {uuid.UUID(run): ident for ident, run in rows}

    async def _by_ids(
        self, table: Any, workspace_id: uuid.UUID, ids: Iterable[uuid.UUID]
    ) -> Sequence[Any]:
        wanted = list(set(ids))
        if not wanted:
            return []
        return (
            await self._session.scalars(
                select(table).where(table.workspace_id == workspace_id, table.id.in_(wanted))
            )
        ).all()

    # ── kept ────────────────────────────────────────────────────────────────

    async def write(self, rows: Sequence[Mapping[str, Any]]) -> None:
        """Each execution's row, written again whole: the same calls read
        twice write the same row."""
        if not rows:
            return
        statement = insert(UsageRecord).values(list(rows))
        kept = {"id", "workspace_id", "execution", "created_at"}
        statement = statement.on_conflict_do_update(
            constraint="uq_usage_records_execution",
            set_={
                column.name: statement.excluded[column.name]
                for column in UsageRecord.__table__.columns
                if column.name not in kept
            },
        )
        await self._session.execute(statement)

    async def records(
        self, workspace_id: uuid.UUID, *, intention_id: uuid.UUID
    ) -> Sequence[UsageRecord]:
        return (
            await self._session.scalars(
                select(UsageRecord)
                .where(
                    UsageRecord.workspace_id == workspace_id,
                    UsageRecord.intention_id == intention_id,
                )
                .order_by(UsageRecord.started_at)
            )
        ).all()


def _read_run(intention: Intention) -> uuid.UUID | None:
    read_by = (intention.understanding or {}).get("read_by")
    run = read_by.get("run_id") if isinstance(read_by, dict) else None
    return _uuid(run) if isinstance(run, str) else None
