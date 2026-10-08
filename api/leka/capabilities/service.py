"""Agents run for one workspace (LEKA-395): asked, read, cancelled — what
the API calls. How a run runs is runs.py; what a run is, runtime.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.catalogue import CatalogueService
from leka.capabilities.models import AgentRun, AgentRunEvent
from leka.capabilities.repository import CapabilityRunRepository
from leka.capabilities.runs import Steps, now_or, refusal_of
from leka.capabilities.runtime import Refusal, RunStatus, delivered
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


class AgentRuntime:
    """Agents run for one workspace: asked, read, cancelled."""

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
        now: datetime | None = None,
    ) -> AgentRun:
        """Kept queued — RunRefusedError when it cannot run here, by this
        person, with this. The caller commits, then queues it (queue_run)."""
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
            status=RunStatus.QUEUED.value,
            inputs=dict(inputs),
            requested_by=by,
            intention_id=intention_id,
            context_id=context_id,
            format=format_,
            detail={"pending": list(pending)} if pending else {},
            tool_calls=0,
            queued_at=moment,
        )
        self._runs.add(run)
        await self._session.flush()
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
        if RunStatus(run.status) not in (RunStatus.QUEUED, RunStatus.RUNNING):
            raise RunFinishedError
        moment = now_or(now)
        run.status = RunStatus.CANCELLED.value
        run.finished_at = moment
        run.error = None
        run.detail = {**run.detail, "cancelled_by": str(by)}
        Steps(self._session, run, await self._runs.last_seq(run.id)).add("cancelled", by=str(by))
        await self._session.flush()
        return run
