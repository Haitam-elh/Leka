"""Running a workflow (LEKA-397): asked, queued, its steps run one after the
other in the order of their dependencies, each kept — and a failed run
retried from where it failed.

    POST /workflow-runs ──▶ WorkflowService.start: the workflow as the
                            catalogue holds it, usable here by this person,
                            given what it takes — refused, said why — or
                            kept queued with its steps pending, its steps as
                            they are now (`spec`): what it runs whatever the
                            file says later
    run_workflow ─────────▶ execute_workflow:
        1. claimed: queued → running, by one worker
        2. the person who asked, still allowed — their role read now
        3. until nothing is left (workflow.next_steps):
             a step that stops it failed       the run fails, what was not
                                               run is not reached
             a step whose condition fails      skipped
             a step that can run               its capability checked as it
                                               stands for this person; run by
                                               the executor of its kind — an
                                               agent here, LEKA's own rules
                                               in leka.intentions — retried
                                               while its attempts last and
                                               its failure says it may be
             cancelled meanwhile               stops between steps
    retry ────────────────▶ a failed run queued again: its failed and not
                            reached steps pending again, what succeeded kept
    THE SWEEP (workflow-runs-sweep): a run no worker will finish — failed,
    `abandoned`.

Every step's state is a row (workflow_run_steps); every move, an event
(workflow_run_events, append-only).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import JobQueue, enqueue_job
from leka.capabilities.catalogue import CatalogueService, Entry
from leka.capabilities.definition import Definition, Kind, check_input
from leka.capabilities.models import (
    AgentRun,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStep,
)
from leka.capabilities.registry import find, find_workflow
from leka.capabilities.runs import execute_run, permissions_of
from leka.capabilities.runtime import Refusal
from leka.capabilities.service import AgentRuntime, NotYoursError, RunFinishedError, RunRefusedError
from leka.capabilities.skills import SkillRuntime
from leka.capabilities.workflow import (
    ENDED,
    Ended,
    RunStatus,
    Step,
    StepStatus,
    Workflow,
    from_spec,
    given_to,
    next_steps,
    order,
    outcome,
    skill_of,
)
from leka.db import (
    hidden_entities,
    load_schema,
    session_factory,
    system_scope,
    workspace_scope,
)
from leka.governance import hidden_on_behalf
from leka.platform import MembershipRepository

logger = structlog.get_logger(__name__)

RUN_JOB = "leka.capabilities.workflow_runs.run_workflow"
ABANDONED = timedelta(hours=1)
FORGOTTEN = timedelta(hours=6)
# What is kept of what a step delivered.
OUTPUT_KEPT = 4000
# Failures a retry cannot mend: the person, the workflow itself.
FINAL = frozenset({"not_permitted", "gone"})


def now_or(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


# ── steps, by kind ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StepCall:
    """What a step's executor is handed."""

    workspace_id: uuid.UUID
    run_id: uuid.UUID
    step: Step
    capability: Definition
    given: Mapping[str, object]
    intention_id: uuid.UUID | None
    requested_by: uuid.UUID | None
    permissions: frozenset[str]
    attempt: int


@dataclass(frozen=True)
class StepResult:
    """What came of one attempt: succeeded or failed — and whether trying
    again may mend it."""

    status: str  # succeeded, failed
    codes: tuple[str, ...] = ()
    summary: str | None = None
    ref: str | None = None
    output: Mapping[str, object] = field(default_factory=dict)
    error: str | None = None
    retryable: bool = True


StepExecutor = Callable[[StepCall], Awaitable[StepResult]]
_executors: dict[Kind, StepExecutor] = {}


def register_step(kind: Kind, executor: StepExecutor) -> None:
    """How steps of a kind run — LEKA's own rules are registered by
    leka.intentions, as it provides them to the catalogue."""
    _executors[kind] = executor


async def agent_step(call: StepCall) -> StepResult:
    """An agent, run as a step: a run of its own (agent_runs), executed
    here and now; what it delivered, the step's."""
    if call.requested_by is None:
        return StepResult("failed", error="not_permitted", retryable=False)
    async with session_factory() as session:
        try:
            run = await AgentRuntime(session, call.workspace_id).start(
                call.capability.key,
                call.given,
                by=call.requested_by,
                permissions=call.permissions,
                intention_id=call.intention_id,
            )
        except RunRefusedError as refused:
            return StepResult("failed", error=refused.refusal.code, retryable=False)
        await session.commit()
        run_id = run.id
    ended = await execute_run(call.workspace_id, run_id)
    async with session_factory() as session:
        found = await session.get(AgentRun, run_id)
    ref = f"agent_run:{run_id}"
    if found is None or found.status != "succeeded":
        error = found.error if found is not None else str(ended.get("status"))
        return StepResult(
            "failed", ref=ref, error=error, retryable=error in ("no_model", "timeout", "error")
        )
    return StepResult(
        "succeeded",
        summary=(found.output or "")[:300],
        ref=ref,
        output={"text": (found.output or "")[:OUTPUT_KEPT], "format": found.format},
    )


register_step(Kind.AGENT, agent_step)


# A skill's output kept with its step, at most (characters).
SKILL_OUTPUT_KEPT = 20_000


async def skill_step(
    session: AsyncSession,
    run: WorkflowRun,
    step: Step,
    key: str,
    permissions: frozenset[str],
) -> StepResult:
    """A skill, run as a step (LEKA-401): through the skill runtime, with
    what the person who asked may do — checked, kept about this run. What it
    concluded — its signals — becomes the step's codes, which a later step's
    condition reads (`found`)."""
    outcome = await SkillRuntime(
        session,
        run.workspace_id,
        permissions=permissions,
        by=run.requested_by,
        caller=f"workflow:{run.key}",
        ref=f"workflow_run:{run.id}",
    ).run(key, given_to(step, run.inputs))
    ref = f"skill_run:{outcome.run_id}"
    if not outcome.ok:
        return StepResult(
            "failed",
            ref=ref,
            error=(outcome.reason or outcome.status)[:60],
            output={"message": outcome.message, "errors": [dict(e) for e in outcome.errors]},
            retryable=outcome.status == "timed_out" or outcome.reason == "error",
        )
    said = outcome.said()
    size = len(json.dumps(said, ensure_ascii=False, default=str))
    signals = outcome.signals
    worth = [s for s in signals if s.level != "info"] or list(signals)
    return StepResult(
        "succeeded",
        codes=tuple(dict.fromkeys(s.code for s in signals)),
        summary=" ".join(s.text for s in worth[:3])[:300] or None,
        ref=ref,
        output=said if size <= SKILL_OUTPUT_KEPT else {"left_out": size},
    )


# ── kept ────────────────────────────────────────────────────────────────────


class Events:
    def __init__(self, session: AsyncSession, run: WorkflowRun, seq: int) -> None:
        self._session = session
        self._run = run
        self._seq = seq

    def add(self, kind: str, step: str | None = None, **detail: object) -> None:
        self._seq += 1
        self._session.add(
            WorkflowRunEvent(
                workspace_id=self._run.workspace_id,
                id=uuid.uuid4(),
                run_id=self._run.id,
                seq=self._seq,
                kind=kind,
                step=step,
                at=now_or(),
                detail=detail,
            )
        )


class WorkflowRepository:
    """One workspace's workflow runs."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def run(self, run_id: uuid.UUID, *, lock: bool = False) -> WorkflowRun | None:
        query = select(WorkflowRun).where(
            WorkflowRun.workspace_id == self._workspace_id, WorkflowRun.id == run_id
        )
        found: WorkflowRun | None = await self._session.scalar(
            query.with_for_update() if lock else query
        )
        return found

    async def runs(
        self, *, key: str | None, status: str | None, limit: int
    ) -> Sequence[WorkflowRun]:
        query = (
            select(WorkflowRun)
            .where(WorkflowRun.workspace_id == self._workspace_id)
            .order_by(WorkflowRun.queued_at.desc(), WorkflowRun.id)
            .limit(limit)
        )
        if key is not None:
            query = query.where(WorkflowRun.key == key)
        if status is not None:
            query = query.where(WorkflowRun.status == status)
        return (await self._session.scalars(query)).all()

    async def steps(self, run_id: uuid.UUID) -> Sequence[WorkflowRunStep]:
        return (
            await self._session.scalars(
                select(WorkflowRunStep)
                .where(
                    WorkflowRunStep.workspace_id == self._workspace_id,
                    WorkflowRunStep.run_id == run_id,
                )
                .order_by(WorkflowRunStep.position)
            )
        ).all()

    async def events(self, run_id: uuid.UUID) -> Sequence[WorkflowRunEvent]:
        return (
            await self._session.scalars(
                select(WorkflowRunEvent)
                .where(
                    WorkflowRunEvent.workspace_id == self._workspace_id,
                    WorkflowRunEvent.run_id == run_id,
                )
                .order_by(WorkflowRunEvent.at, WorkflowRunEvent.seq)
            )
        ).all()

    async def last_seq(self, run_id: uuid.UUID) -> int:
        found = await self._session.scalar(
            select(func.max(WorkflowRunEvent.seq)).where(WorkflowRunEvent.run_id == run_id)
        )
        return int(found or 0)

    async def claim(self, run_id: uuid.UUID, *, at: datetime) -> bool:
        claimed = await self._session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.workspace_id == self._workspace_id,
                WorkflowRun.id == run_id,
                WorkflowRun.status == RunStatus.QUEUED.value,
            )
            .values(status=RunStatus.RUNNING.value, started_at=at)
        )
        return bool(claimed.rowcount)  # type: ignore[attr-defined]


def workflow_of(run: WorkflowRun) -> Workflow:
    """The workflow a run runs: its steps as they were when it was asked."""
    return from_spec(run.key, run.version, run.spec)


# ── asked ───────────────────────────────────────────────────────────────────


def refusal_of(entry: Entry | None, inputs: Mapping[str, object]) -> Refusal | None:
    """Why it cannot run here, by this person, with this."""
    if entry is None:
        return Refusal("not_found")
    if entry.definition.kind is not Kind.WORKFLOW or find_workflow(entry.definition.key) is None:
        return Refusal("not_a_workflow")
    if not entry.availability.available:
        codes = entry.availability.codes
        reasons = tuple({"code": r.code, **r.detail} for r in entry.availability.reasons)
        return Refusal("not_permitted" if codes == ("not_permitted",) else "unavailable", reasons)
    errors = check_input(entry.definition.contract, inputs)
    if errors:
        return Refusal("invalid_input", tuple({"name": e.name, "code": e.code} for e in errors))
    return None


class WorkflowService:
    """Workflows run for one workspace: asked, read, cancelled, retried."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._runs = WorkflowRepository(session, workspace_id)
        self._catalogue = CatalogueService(session, workspace_id)

    async def start(
        self,
        key: str,
        inputs: Mapping[str, object],
        *,
        by: uuid.UUID,
        permissions: frozenset[str],
        intention_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> WorkflowRun:
        """Kept queued, its steps pending — RunRefusedError otherwise. The
        caller commits, then queues it (queue_workflow)."""
        entry = await self._catalogue.entry(key, permissions=permissions)
        refused = refusal_of(entry, inputs)
        if refused is not None:
            raise RunRefusedError(refused)
        workflow = find_workflow(key)
        assert entry is not None and workflow is not None
        rules = [
            s.id
            for s in workflow.steps
            if (used := find(s.uses)) is not None and used.kind is Kind.RULES
        ]
        if rules and intention_id is None:
            # LEKA's own rules read an intention's context: there must be one.
            raise RunRefusedError(Refusal("needs_intention", ({"steps": rules},)))
        moment = now_or(now)
        run = WorkflowRun(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            key=workflow.key,
            version=workflow.version,
            spec=workflow.spec(),
            status=RunStatus.QUEUED.value,
            inputs=dict(inputs),
            requested_by=by,
            intention_id=intention_id,
            retries=0,
            queued_at=moment,
        )
        self._session.add(run)
        await self._session.flush()
        for position, step_id in enumerate(order(workflow)):
            step = workflow.step(step_id)
            self._session.add(
                WorkflowRunStep(
                    workspace_id=self._workspace_id,
                    id=uuid.uuid4(),
                    run_id=run.id,
                    step=step.id,
                    position=position,
                    uses=step.uses,
                    status=StepStatus.PENDING.value,
                    attempts=0,
                    output={},
                )
            )
        Events(self._session, run, 0).add("queued", by=str(by))
        await self._session.flush()
        return run

    async def runs(
        self, *, key: str | None = None, status: str | None = None, limit: int = 50
    ) -> Sequence[WorkflowRun]:
        return await self._runs.runs(key=key, status=status, limit=limit)

    async def run(
        self, run_id: uuid.UUID
    ) -> tuple[WorkflowRun, Sequence[WorkflowRunStep], Sequence[WorkflowRunEvent]] | None:
        found = await self._runs.run(run_id)
        if found is None:
            return None
        return found, await self._runs.steps(run_id), await self._runs.events(run_id)

    async def cancel(
        self, run_id: uuid.UUID, *, by: uuid.UUID, anyones: bool, now: datetime | None = None
    ) -> WorkflowRun | None:
        """Cancelled — between two steps if it runs: the step running ends,
        nothing after it starts."""
        run = await self._runs.run(run_id, lock=True)
        if run is None:
            return None
        if run.requested_by != by and not anyones:
            raise NotYoursError
        if run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
            raise RunFinishedError
        run.status = RunStatus.CANCELLED.value
        run.finished_at = now_or(now)
        for step in await self._runs.steps(run_id):
            if step.status == StepStatus.PENDING:
                step.status = StepStatus.NOT_REACHED.value
                step.reason = "cancelled"
        Events(self._session, run, await self._runs.last_seq(run_id)).add("cancelled", by=str(by))
        await self._session.flush()
        return run

    async def retry(self, run_id: uuid.UUID, *, by: uuid.UUID, anyones: bool) -> WorkflowRun | None:
        """A failed run queued again from where it failed: its failed and
        not reached steps pending again, what succeeded or was skipped kept.
        Not when what failed it cannot be mended by trying again (FINAL)."""
        run = await self._runs.run(run_id, lock=True)
        if run is None:
            return None
        if run.requested_by != by and not anyones:
            raise NotYoursError
        if run.status != RunStatus.FAILED or (run.error or "") in FINAL:
            raise RunFinishedError
        for step in await self._runs.steps(run_id):
            if step.status in (StepStatus.FAILED, StepStatus.NOT_REACHED, StepStatus.RUNNING):
                step.status = StepStatus.PENDING.value
                step.attempts = 0
                step.reason = None
                step.output = {}
                step.started_at = None
                step.finished_at = None
        run.status = RunStatus.QUEUED.value
        run.error = None
        run.failed_step = None
        run.finished_at = None
        run.retries += 1
        Events(self._session, run, await self._runs.last_seq(run_id)).add(
            "retried", by=str(by), retry=run.retries
        )
        await self._session.flush()
        return run


async def queue_workflow(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    job = await enqueue_job(
        RUN_JOB,
        str(workspace_id),
        str(run_id),
        for_workspace_id=workspace_id,
        queue=JobQueue.HIGH,
        concurrency_key=f"workflow-run:{run_id}",
    )
    return job is not None


# ── a run ──────────────────────────────────────────────────────────────────


async def _end(
    session: AsyncSession,
    run: WorkflowRun,
    steps: Mapping[str, WorkflowRunStep],
    events: Events,
    status: RunStatus,
    *,
    error: str | None = None,
    failed_step: str | None = None,
) -> dict[str, object]:
    for step in steps.values():
        if step.status == StepStatus.PENDING:
            step.status = StepStatus.NOT_REACHED.value
            step.reason = "stopped"
    ended = await session.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run.id, WorkflowRun.status == RunStatus.RUNNING.value)
        .values(status=status.value, error=error, failed_step=failed_step, finished_at=now_or())
    )
    if ended.rowcount:  # type: ignore[attr-defined]
        events.add(status.value, failed_step, error=error)
        await session.commit()
        logger.info("workflow_run_ended", run=str(run.id), key=run.key, status=status.value)
        return {"status": status.value, **({"error": error} if error else {})}
    await session.commit()
    return {"status": "cancelled"}


async def _cancelled(session: AsyncSession, run: WorkflowRun) -> bool:
    status = await session.scalar(select(WorkflowRun.status).where(WorkflowRun.id == run.id))
    return status == RunStatus.CANCELLED


async def _attempt(call: StepCall) -> StepResult:
    executor = _executors.get(call.capability.kind)
    if executor is None:
        return StepResult("failed", error="no_executor", retryable=False)
    try:
        return await executor(call)
    except Exception as error:
        logger.warning("workflow_step_failed", step=call.step.id, exc_info=True)
        return StepResult("failed", error=type(error).__name__)


async def _step(
    session: AsyncSession,
    run: WorkflowRun,
    row: WorkflowRunStep,
    step: Step,
    events: Events,
    permissions: frozenset[str],
) -> StepResult:
    """One step, its attempts — as its capability stands for the person; a
    skill (LEKA-401), through the skill runtime."""
    key = skill_of(step.uses)
    entry: Entry | None = None
    if key is None:
        entry = await CatalogueService(session, run.workspace_id).entry(
            step.uses, permissions=permissions
        )
        if entry is None or not entry.availability.available:
            why = list(entry.availability.codes) if entry is not None else ["not_found"]
            events.add("step_failed", step.id, error="unavailable", why=why)
            return StepResult("failed", error="unavailable", output={"why": why}, retryable=False)
    result = StepResult("failed", error="not_run")
    for attempt in range(1, step.attempts + 1):
        row.status = StepStatus.RUNNING.value
        row.attempts = attempt
        row.started_at = row.started_at or now_or()
        events.add("step_started", step.id, attempt=attempt)
        await session.commit()
        started = time.monotonic()
        if key is not None:
            result = await skill_step(session, run, step, key, permissions)
        else:
            assert entry is not None  # refused above otherwise
            result = await _attempt(
                StepCall(
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    step=step,
                    capability=entry.definition,
                    given=given_to(step, run.inputs),
                    intention_id=run.intention_id,
                    requested_by=run.requested_by,
                    permissions=permissions,
                    attempt=attempt,
                )
            )
        ms = int((time.monotonic() - started) * 1000)
        if result.status == "succeeded" or not result.retryable or attempt == step.attempts:
            events.add(
                "step_succeeded" if result.status == "succeeded" else "step_failed",
                step.id,
                attempt=attempt,
                error=result.error,
                ms=ms,
            )
            break
        events.add("step_retried", step.id, attempt=attempt, error=result.error, ms=ms)
    return result


async def execute_workflow(workspace_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, object]:
    """One run, end to end — idempotent: a run no longer queued is not run
    again."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            repo = WorkflowRepository(session, workspace_id)
            if not await repo.claim(run_id, at=now_or()):
                await session.rollback()
                return {"status": "not_queued"}
            run = await repo.run(run_id)
            assert run is not None
            await session.refresh(run)
            events = Events(session, run, await repo.last_seq(run_id))
            events.add("started", retry=run.retries)
            await session.commit()
            steps = {s.step: s for s in await repo.steps(run_id)}
            # Its steps see only what the person who asked may (LEKA-402).
            hidden = await hidden_on_behalf(session, workspace_id, run.requested_by)
            try:
                with hidden_entities(hidden):
                    return await _drive(session, run, steps, events)
            except Exception as error:
                logger.exception("workflow_run_failed", run=str(run_id), key=run.key)
                await session.rollback()
                await session.refresh(run)
                return await _end(
                    session, run, steps, events, RunStatus.FAILED, error=type(error).__name__[:40]
                )


async def _drive(
    session: AsyncSession,
    run: WorkflowRun,
    steps: Mapping[str, WorkflowRunStep],
    events: Events,
) -> dict[str, object]:
    workflow = workflow_of(run)
    seat = (
        await MembershipRepository(session, run.workspace_id).get_for_user(run.requested_by)
        if run.requested_by is not None
        else None
    )
    if seat is None:
        return await _end(session, run, steps, events, RunStatus.FAILED, error="not_permitted")
    permissions = permissions_of(seat.role)
    while True:
        statuses = {k: StepStatus(s.status) for k, s in steps.items()}
        ended = {k: Ended(s.status, codes_of(s)) for k, s in steps.items() if s.status in ENDED}
        nxt = next_steps(workflow, statuses, ended, run.inputs)
        if nxt.done:
            status = outcome(statuses, workflow)
            return await _end(
                session,
                run,
                steps,
                events,
                status,
                error="step_failed" if nxt.failed else None,
                failed_step=nxt.failed,
            )
        for step_id in nxt.skip:
            steps[step_id].status = StepStatus.SKIPPED.value
            steps[step_id].reason = "condition_false"
            events.add("step_skipped", step_id, reason="condition_false")
        await session.commit()
        for step_id in nxt.run:
            if await _cancelled(session, run):
                return {"status": "cancelled"}
            row, step = steps[step_id], workflow.step(step_id)
            result = await _step(session, run, row, step, events, permissions)
            row.status = (
                StepStatus.SUCCEEDED.value
                if result.status == "succeeded"
                else StepStatus.FAILED.value
            )
            row.reason = None if result.status == "succeeded" else (result.error or "failed")[:60]
            row.output = _kept(result)
            row.finished_at = now_or()
            await session.commit()
            if row.status == StepStatus.FAILED and step.on_failure == "stop":
                break


def codes_of(step: WorkflowRunStep) -> frozenset[str]:
    """What a step that ended found, as conditions read it."""
    said = step.output.get("codes")
    return frozenset(str(c) for c in said) if isinstance(said, list) else frozenset()


def _kept(result: StepResult) -> dict[str, Any]:
    said: dict[str, Any] = {"codes": list(result.codes), **dict(result.output)}
    if result.summary is not None:
        said["summary"] = result.summary
    if result.ref is not None:
        said["ref"] = result.ref
    if result.error is not None:
        said["error"] = result.error
        said["retryable"] = result.retryable
    return said


def run_workflow(workspace_id: str, run_id: str) -> dict[str, object]:
    """Entry point for the job runner — every module imported first, so
    that each registers how its steps run."""
    load_schema()
    return asyncio.run(execute_workflow(uuid.UUID(workspace_id), uuid.UUID(run_id)))


# ── the sweep ──────────────────────────────────────────────────────────────


async def sweep_workflows(*, now: datetime | None = None, limit: int = 200) -> dict[str, int]:
    """Every run no worker will finish, failed — `abandoned`. Retried, it
    goes on from where it was."""
    moment = now_or(now)
    with system_scope():
        async with session_factory() as session:
            rows = await session.execute(
                select(WorkflowRun.workspace_id, WorkflowRun.id)
                .where(
                    (
                        (WorkflowRun.status == RunStatus.RUNNING.value)
                        & (WorkflowRun.started_at < moment - ABANDONED)
                    )
                    | (
                        (WorkflowRun.status == RunStatus.QUEUED.value)
                        & (WorkflowRun.queued_at < moment - FORGOTTEN)
                    )
                )
                .limit(limit)
            )
            stale = rows.tuples().all()
    swept = 0
    for workspace_id, run_id in stale:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                repo = WorkflowRepository(session, workspace_id)
                run = await repo.run(run_id, lock=True)
                if run is None or run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
                    continue
                for step in await repo.steps(run_id):
                    if step.status in (StepStatus.PENDING, StepStatus.RUNNING):
                        step.status = StepStatus.NOT_REACHED.value
                        step.reason = "abandoned"
                run.status = RunStatus.FAILED.value
                run.error = "abandoned"
                run.finished_at = moment
                Events(session, run, await repo.last_seq(run_id)).add("failed", error="abandoned")
                await session.commit()
                swept += 1
    logger.info("workflow_runs_swept", abandoned=swept)
    return {"abandoned": swept}


def run_workflows_sweep() -> dict[str, int]:
    return asyncio.run(sweep_workflows())
