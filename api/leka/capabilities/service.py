"""What the API calls: agents run for one workspace (LEKA-395) — asked,
read, cancelled; held for approval, approved, rejected (LEKA-406); how a
run runs is runs.py, what a run is, runtime.py — and intentions routed to a
capability (LEKA-398), how router.py decides.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.catalogue import CatalogueService
from leka.capabilities.models import AgentRun, AgentRunEvent, CapabilityRouting
from leka.capabilities.repository import CapabilityRunRepository, RoutingRepository
from leka.capabilities.router import RouteQuery, decision_said, query_said, route
from leka.capabilities.runs import Steps, now_or, refusal_of
from leka.capabilities.runtime import Refusal, RunStatus, delivered
from leka.capabilities.schemas import RoutingRead
from leka.context import ContextRepository


class RunRefusedError(Exception):
    """It cannot run, said why — nothing kept."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(refusal.code)
        self.refusal = refusal


class NotYoursError(Exception):
    """Only who asked it, or an admin, may cancel a run."""


class RunFinishedError(Exception):
    """A run that ended cannot be cancelled."""


class NotAwaitingError(Exception):
    """Only a run waiting for approval is approved or rejected (LEKA-406)."""


class OwnRunError(Exception):
    """Who asked a run does not approve it (LEKA-406)."""


class AgentRuntime:
    """Agents run for one workspace: asked, read, cancelled — and, when an
    approval control holds one (LEKA-406), approved or rejected."""

    def __init__(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        *,
        catalogue: CatalogueService | None = None,
    ) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._runs = CapabilityRunRepository(session, workspace_id)
        self._catalogue = catalogue or CatalogueService(session, workspace_id)

    async def start(
        self,
        key: str,
        inputs: Mapping[str, object],
        *,
        by: uuid.UUID,
        permissions: frozenset[str],
        intention_id: uuid.UUID | None = None,
        context_id: uuid.UUID | None = None,
        held_by: str | None = None,
        now: datetime | None = None,
    ) -> AgentRun:
        """Kept queued — RunRefusedError when it cannot run here, by this
        person, with this. The caller commits, then queues it (queue_run).
        Held by an approval control (`held_by`, its name — LEKA-406), it
        waits instead: approve() queues it."""
        entry = await self._catalogue.entry(key, permissions=permissions, user_id=by)
        refused = refusal_of(entry, inputs)
        if refused is not None:
            raise RunRefusedError(refused)
        assert entry is not None  # refusal_of said not_found otherwise
        if context_id is not None and (
            await ContextRepository(self._session, self._workspace_id).context(context_id) is None
        ):
            raise RunRefusedError(Refusal("unknown_context"))
        definition = entry.definition
        format_, pending = delivered(definition)
        moment = now_or(now)
        run = AgentRun(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            key=definition.key,
            version=definition.version,
            status=(RunStatus.AWAITING_APPROVAL if held_by else RunStatus.QUEUED).value,
            inputs=dict(inputs),
            requested_by=by,
            intention_id=intention_id,
            context_id=context_id,
            format=format_,
            detail={
                **({"pending": list(pending)} if pending else {}),
                **({"held_by": held_by} if held_by else {}),
            },
            tool_calls=0,
            queued_at=moment,
        )
        self._runs.add(run)
        await self._session.flush()
        if held_by:
            Steps(self._session, run, 0).add("held", by=str(by), control=held_by)
        else:
            Steps(self._session, run, 0).add("queued", by=str(by))
        await self._session.flush()
        return run

    async def runs(
        self, *, key: str | None = None, status: str | None = None, limit: int = 50
    ) -> Sequence[AgentRun]:
        return await self._runs.runs(key=key, status=status, limit=limit)

    async def run(
        self, run_id: uuid.UUID
    ) -> tuple[AgentRun, Sequence[AgentRunEvent], tuple[int, int, int, float | None]] | None:
        """One run, its steps, what its model calls took."""
        found = await self._runs.run(run_id)
        if found is None:
            return None
        return found, await self._runs.events(run_id), await self._runs.usage(run_id)

    async def cancel(
        self, run_id: uuid.UUID, *, by: uuid.UUID, anyones: bool, now: datetime | None = None
    ) -> AgentRun | None:
        """Cancelled — queued, it never runs; running, what it delivers is
        not kept. Only who asked it, or who may handle anyone's
        (`anyones`)."""
        run = await self._runs.run(run_id, lock=True)
        if run is None:
            return None
        if run.requested_by != by and not anyones:
            raise NotYoursError
        if RunStatus(run.status) not in (
            RunStatus.AWAITING_APPROVAL,
            RunStatus.QUEUED,
            RunStatus.RUNNING,
        ):
            raise RunFinishedError
        moment = now_or(now)
        run.status = RunStatus.CANCELLED.value
        run.finished_at = moment
        run.error = None
        run.detail = {**run.detail, "cancelled_by": str(by)}
        Steps(self._session, run, await self._runs.last_seq(run.id)).add("cancelled", by=str(by))
        await self._session.flush()
        return run

    async def decide(
        self,
        run_id: uuid.UUID,
        *,
        by: uuid.UUID,
        approve: bool,
        note: str | None = None,
        now: datetime | None = None,
    ) -> AgentRun | None:
        """A held run approved — queued: the caller commits, then queues it
        (queue_run) — or rejected: cancelled, never run. Never by who asked it
        (OwnRunError); only one waiting (NotAwaitingError)."""
        run = await self._runs.run(run_id, lock=True)
        if run is None:
            return None
        if RunStatus(run.status) is not RunStatus.AWAITING_APPROVAL:
            raise NotAwaitingError
        if run.requested_by == by:
            raise OwnRunError
        said = {"by": str(by), **({"note": note} if note else {})}
        steps = Steps(self._session, run, await self._runs.last_seq(run.id))
        if approve:
            run.status = RunStatus.QUEUED.value
            run.detail = {**run.detail, "approved_by": str(by)}
            steps.add("approved", **said)
        else:
            run.status = RunStatus.CANCELLED.value
            run.finished_at = now_or(now)
            run.detail = {**run.detail, "rejected_by": str(by)}
            steps.add("rejected", **said)
        await self._session.flush()
        return run


class CapabilityRouter:
    """Intentions routed to capabilities, for one workspace and one person —
    each decision kept (LEKA-398)."""

    def __init__(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        *,
        catalogue: CatalogueService | None = None,
    ) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._routings = RoutingRepository(session, workspace_id)
        self._catalogue = catalogue or CatalogueService(session, workspace_id)

    async def route(
        self,
        query: RouteQuery,
        *,
        permissions: frozenset[str],
        by: uuid.UUID | None,
        subject_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> CapabilityRouting:
        """Routed, as the catalogue stands for this person now — kept."""
        entries = await self._catalogue.entries(permissions=permissions)
        decided = route(
            query,
            [e.definition for e in entries],
            {e.definition.key: e.availability for e in entries},
        )
        row = CapabilityRouting(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            subject_type="intention" if subject_id is not None else "request",
            subject_id=subject_id,
            version=decided.version,
            outcome=decided.outcome,
            selected=[c.key for c in decided.selected],
            query=query_said(query),
            decision=decision_said(decided),
            routed_by=by,
            at=now_or(now),
        )
        self._routings.add(row)
        await self._session.flush()
        return row

    async def latest(self, subject_id: uuid.UUID) -> CapabilityRouting | None:
        return await self._routings.latest(subject_id)


def routing_read(row: CapabilityRouting) -> RoutingRead:
    """A routing, as kept, for the API."""
    return RoutingRead.model_validate(
        {
            **row.decision,
            "id": row.id,
            "subject_type": row.subject_type,
            "subject_id": row.subject_id,
            "version": row.version,
            "outcome": row.outcome,
            "selected": row.selected,
            "query": row.query,
            "at": row.at,
        }
    )
