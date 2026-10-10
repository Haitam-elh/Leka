"""Approved decisions carried out (LEKA-391): planned, checked, run through
the systems the workspace authorized — or by a person — every step's
evidence kept, the intention moved as it goes.

    approved ──▶ plan()    the plan of the approved decision (execution.py)
             ──▶ start()   checked now (or at its moment): run, or scheduled
                           — the intention executing, or scheduled
             ──▶ advance() step by step: a person's step waits for them; an
                           authorized system's is called by the job, signed;
                           what it answered kept, said as it is
             ──▶ all done: verifying (LEKA-392 verifies); one failed: the
                           rest skipped, the intention failed — retried by a
                           new plan of what did not succeed
    cancel() ──▶ before it runs: unscheduled, the intention approved again;
                 while it runs: what has not started cancelled, the
                 intention failed — what ran stays said

A call to a system is never taken for success unless the system said so;
an answer that it accepted the work waits for a person to confirm it.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time as clock
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import enqueue_job
from leka.connectors import BlockedAddressError, PublicTransport
from leka.core import breaker
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import Target, audit
from leka.intentions.approval import approvers_of
from leka.intentions.decisions import DecisionStatus
from leka.intentions.execution import (
    DELIVERY,
    SIGNATURE,
    Endpoint,
    Outcome,
    Situation,
    StepPlan,
    blocking,
    body_of,
    checks,
    excerpt,
    outcome_of,
    plan_of,
    scheduled_for,
    sign,
)
from leka.intentions.lifecycle import Actor, IntentionStatus
from leka.intentions.models import (
    ActionEndpoint,
    IntentionDecision,
    IntentionPlan,
    IntentionPlanEvent,
    IntentionPlanStep,
)
from leka.intentions.repository import IntentionRepository
from leka.intentions.schemas import (
    ActionEndpointRead,
    ExpectationRead,
    IntentionPlanEventRead,
    IntentionPlanRead,
    IntentionPlanStepRead,
    PlanCheckRead,
)
from leka.intentions.service import IntentionService
from leka.intentions.verification import VerificationService, expected
from leka.knowledge import Entity
from leka.platform import Membership, Role, secret_box

logger = structlog.get_logger(__name__)

S = IntentionStatus
PLAN_JOB = "leka.intentions.actions.run_plan"
# A system has this long to answer.
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
ACTIVE = ("planned", "scheduled", "running")
APPROVERS = (Role.ADMIN, Role.OWNER)
GONE = ("removed", "archived")


class PlanRefusedError(Exception):
    """What cannot be done to a plan now: its code says why; failed checks
    are said with it."""

    def __init__(
        self, code: str, message: str, failed: Sequence[Mapping[str, object]] = ()
    ) -> None:
        super().__init__(message)
        self.code = code
        self.failed = list(failed)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def concurrency_key(plan_id: uuid.UUID) -> str:
    return f"intention-plan:{plan_id}"


def endpoint_of(row: ActionEndpoint) -> Endpoint:
    return Endpoint(
        id=row.id,
        name=row.name,
        actions=frozenset(row.actions),
        environments=frozenset(row.environments),
        targets=frozenset(uuid.UUID(t) for t in row.targets),
        enabled=row.enabled,
    )


def endpoint_read(row: ActionEndpoint) -> ActionEndpointRead:
    return ActionEndpointRead.model_validate(row)


def _step_plan(step: IntentionPlanStep) -> StepPlan:
    return StepPlan(
        position=step.position,
        proposal_id=step.proposal_id,
        action=step.action,
        targets=tuple({k: str(v) for k, v in t.items()} for t in step.targets),
        environment=step.environment,
        constraints=tuple(dict(c) for c in step.constraints),
        executor=step.executor,
        endpoint_id=step.endpoint_id,
    )


def plan_read(
    plan: IntentionPlan,
    steps: Sequence[IntentionPlanStep],
    events: Sequence[IntentionPlanEvent],
    now: datetime | None = None,
) -> IntentionPlanRead:
    suggested = (
        scheduled_for([_step_plan(s) for s in steps], _now(now), _zone(plan.timezone))
        if plan.status == "planned"
        else None
    )
    return IntentionPlanRead(
        id=plan.id,
        intention_id=plan.intention_id,
        decision_id=plan.decision_id,
        number=plan.number,
        revision=plan.revision,
        status=plan.status,
        created_by=plan.created_by,
        started_by=plan.started_by,
        timezone=plan.timezone,
        scheduled_for=plan.scheduled_for,
        suggested_for=suggested,
        started_at=plan.started_at,
        finished_at=plan.finished_at,
        created_at=plan.created_at,
        checks=[PlanCheckRead.model_validate(c) for c in plan.checks],
        expectations=[ExpectationRead.model_validate(e) for e in plan.expectations],
        error=plan.error,
        steps=[IntentionPlanStepRead.model_validate(s) for s in steps],
        events=[IntentionPlanEventRead.model_validate(e) for e in events],
    )


# ── the systems a workspace authorized ──────────────────────────────────────


class EndpointService:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def list(self) -> list[ActionEndpointRead]:
        rows = await self._session.scalars(
            select(ActionEndpoint)
            .where(ActionEndpoint.workspace_id == self._workspace_id)
            .order_by(ActionEndpoint.name)
        )
        return [endpoint_read(r) for r in rows]

    async def get(self, endpoint_id: uuid.UUID) -> ActionEndpoint | None:
        row = await self._session.get(ActionEndpoint, endpoint_id)
        return row if row is not None and row.workspace_id == self._workspace_id else None

    async def create(
        self,
        *,
        name: str,
        url: str,
        actions: Sequence[str],
        environments: Sequence[str],
        targets: Sequence[uuid.UUID],
        by: uuid.UUID,
    ) -> tuple[ActionEndpoint, str]:
        """Made, with a signing secret LEKA generates — returned this once,
        kept encrypted."""
        secret = f"lks_{secrets.token_urlsafe(32)}"
        row = ActionEndpoint(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            name=name.strip(),
            url=url,
            secret_ciphertext=secret_box.encrypt(secret),
            actions=sorted(set(actions)),
            environments=sorted(set(environments)),
            targets=[str(t) for t in dict.fromkeys(targets)],
            enabled=True,
            created_by=by,
        )
        self._session.add(row)
        await self._session.flush()
        return row, secret

    async def update(self, row: ActionEndpoint, change: Mapping[str, object]) -> ActionEndpoint:
        if change.get("name") is not None:
            row.name = str(change["name"]).strip()
        for key in ("actions", "environments"):
            if change.get(key) is not None:
                setattr(row, key, sorted(set(cast("list[str]", change[key]))))
        if change.get("targets") is not None:
            row.targets = [str(t) for t in dict.fromkeys(cast("list[object]", change["targets"]))]
        if change.get("enabled") is not None:
            row.enabled = bool(change["enabled"])
        await self._session.flush()
        return row

    async def delete(self, row: ActionEndpoint) -> None:
        await self._session.delete(row)
        await self._session.flush()


# ── plans ───────────────────────────────────────────────────────────────────


class ActionService:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._intentions = IntentionRepository(session, workspace_id)
        # The plans whose next step is a system's: the route queues their job
        # once it has committed.
        self.to_queue: list[uuid.UUID] = []

    # reading

    async def _steps(self, plan_id: uuid.UUID) -> list[IntentionPlanStep]:
        return list(
            await self._session.scalars(
                select(IntentionPlanStep)
                .where(IntentionPlanStep.plan_id == plan_id)
                .order_by(IntentionPlanStep.position)
            )
        )

    async def _events(self, plan_id: uuid.UUID) -> list[IntentionPlanEvent]:
        return list(
            await self._session.scalars(
                select(IntentionPlanEvent)
                .where(IntentionPlanEvent.plan_id == plan_id)
                .order_by(IntentionPlanEvent.at, IntentionPlanEvent.created_at)
            )
        )

    async def read(self, plan: IntentionPlan, now: datetime | None = None) -> IntentionPlanRead:
        return plan_read(plan, await self._steps(plan.id), await self._events(plan.id), now)

    async def plans(self, intention_id: uuid.UUID) -> list[IntentionPlanRead] | None:
        if await self._intentions.intention(intention_id) is None:
            return None
        rows = await self._session.scalars(
            select(IntentionPlan)
            .where(IntentionPlan.intention_id == intention_id)
            .order_by(IntentionPlan.number.desc())
        )
        return [await self.read(row) for row in rows]

    async def _latest(self, intention_id: uuid.UUID, *, lock: bool = False) -> IntentionPlan | None:
        query = (
            select(IntentionPlan)
            .where(IntentionPlan.intention_id == intention_id)
            .order_by(IntentionPlan.number.desc())
            .limit(1)
        )
        found: IntentionPlan | None = await self._session.scalar(
            query.with_for_update() if lock else query
        )
        return found

    def _event(
        self,
        plan: IntentionPlan,
        kind: str,
        *,
        at: datetime,
        by: uuid.UUID | None = None,
        step: IntentionPlanStep | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self._session.add(
            IntentionPlanEvent(
                workspace_id=self._workspace_id,
                id=uuid.uuid4(),
                plan_id=plan.id,
                step_id=step.id if step else None,
                kind=kind,
                actor=Actor.PERSON if by else Actor.SYSTEM,
                by=by,
                at=at,
                detail=dict(detail or {}),
            )
        )

    async def _endpoints(self) -> list[Endpoint]:
        rows = await self._session.scalars(
            select(ActionEndpoint)
            .where(ActionEndpoint.workspace_id == self._workspace_id)
            .order_by(ActionEndpoint.created_at)
        )
        return [endpoint_of(r) for r in rows]

    # planning

    async def plan(
        self, intention_id: uuid.UUID, *, by: uuid.UUID, now: datetime | None = None
    ) -> IntentionPlanRead | None:
        """The plan of its approved decision — of what did not succeed, when
        it failed and is retried. PlanRefusedError when there is nothing
        approved to carry out, or a plan is already on its way."""
        moment = _now(now)
        intention = await self._intentions.intention(intention_id, lock=True)
        if intention is None:
            return None
        if intention.status not in (S.APPROVED.value, S.FAILED.value) or intention.archived_at:
            raise PlanRefusedError("not_approved", "Only an approved intention is carried out.")
        decision = await self._session.scalar(
            select(IntentionDecision)
            .where(IntentionDecision.intention_id == intention_id)
            .order_by(IntentionDecision.number.desc())
            .limit(1)
        )
        if decision is None or decision.status != DecisionStatus.APPROVED:
            raise PlanRefusedError("not_approved", "No approved decision to carry out.")
        latest = await self._latest(intention_id, lock=True)
        if latest is not None and latest.status in ACTIVE:
            raise PlanRefusedError("already_planned", "A plan is already on its way.")
        proposals = list(decision.proposals)
        if intention.status == S.FAILED.value:
            if latest is None:
                raise PlanRefusedError("not_approved", "Its analysis failed: analyse it again.")
            # What did not succeed, run again — all of it when everything
            # ran but what was expected did not come (LEKA-392).
            if latest.status != "succeeded":
                done = {
                    s.proposal_id for s in await self._steps(latest.id) if s.status == "succeeded"
                }
                proposals = [p for p in proposals if str(p["id"]) not in done]
        steps = plan_of(proposals, await self._endpoints())
        names = {e.id: e.name for e in await self._endpoints()}
        number = (
            await self._session.scalar(
                select(func.max(IntentionPlan.number)).where(
                    IntentionPlan.intention_id == intention_id
                )
            )
            or 0
        ) + 1
        plan = IntentionPlan(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            intention_id=intention_id,
            decision_id=decision.id,
            number=number,
            revision=decision.revision,
            status="planned",
            created_by=by,
            timezone="UTC",
            checks=[],
            detail={"retry_of": str(latest.id)}
            if intention.status == S.FAILED.value and latest
            else {},
            created_at=moment,
        )
        # What should be true once it ran, by default (LEKA-392).
        plan.expectations = await expected(
            self._session, self._workspace_id, [(s.action, s.targets) for s in steps]
        )
        self._session.add(plan)
        await self._session.flush()
        for step in steps:
            self._session.add(
                IntentionPlanStep(
                    workspace_id=self._workspace_id,
                    id=uuid.uuid4(),
                    plan_id=plan.id,
                    position=step.position,
                    proposal_id=step.proposal_id,
                    action=step.action,
                    targets=list(step.targets),
                    environment=step.environment,
                    constraints=list(step.constraints),
                    executor=step.executor,
                    endpoint_id=step.endpoint_id,
                    endpoint_name=names.get(step.endpoint_id) if step.endpoint_id else None,
                    status="pending",
                    evidence={},
                )
            )
        self._event(
            plan,
            "planned",
            at=moment,
            by=by,
            detail={
                "decision_id": str(decision.id),
                "revision": decision.revision,
                "steps": [{"action": s.action, "executor": s.executor} for s in steps],
            },
        )
        await self._session.flush()
        await IntentionService(self._intentions).link(
            intention_id,
            "action",
            plan.id,
            actor=Actor.SYSTEM,
            label=f"#{plan.number}",
            detail={"steps": len(steps)},
            now=moment,
        )
        return await self.read(plan, moment)

    # checking

    async def _situation(
        self, plan: IntentionPlan, steps: Sequence[IntentionPlanStep], at: datetime
    ) -> Situation:
        decision = await self._session.get(IntentionDecision, plan.decision_id)
        if decision is None:
            msg = "a plan without its decision"
            raise LookupError(msg)
        approvers = (
            await approvers_of(self._session, decision)
            if decision.status == DecisionStatus.APPROVED
            else ()
        )
        allowed = set(
            await self._session.scalars(
                select(Membership.user_id).where(
                    Membership.workspace_id == self._workspace_id,
                    Membership.user_id.in_(approvers or [uuid.uuid4()]),
                    Membership.role.in_(APPROVERS),
                )
            )
        )
        ids = {uuid.UUID(str(t["id"])) for s in steps for t in s.targets}
        present = set(
            await self._session.scalars(
                select(Entity.id).where(
                    Entity.workspace_id == self._workspace_id,
                    Entity.id.in_(ids or [uuid.uuid4()]),
                    Entity.lifecycle.not_in(GONE),
                )
            )
        )
        return Situation(
            decision_status=decision.status,
            decision_revision=decision.revision,
            plan_revision=plan.revision,
            approvers=approvers,
            allowed=frozenset(allowed),
            required=decision.required_approvals,
            endpoints={e.id: e for e in await self._endpoints()},
            present=frozenset(present),
            now=at,
            zone=_zone(plan.timezone),
        )

    async def _check(
        self, plan: IntentionPlan, steps: Sequence[IntentionPlanStep], at: datetime
    ) -> list[dict[str, object]]:
        """Every check, kept with the plan; the failing ones returned."""
        found = checks([_step_plan(s) for s in steps], await self._situation(plan, steps, at))
        plan.checks = [c.as_dict() for c in found]
        return [c.as_dict() for c in blocking(found)]

    # starting

    async def start(
        self,
        intention_id: uuid.UUID,
        *,
        by: uuid.UUID,
        at: datetime | None = None,
        timezone: str = "UTC",
        now: datetime | None = None,
    ) -> IntentionPlanRead | None:
        """Checked, then run — or scheduled for `at`. PlanRefusedError, its
        failing checks said, when anything that must hold does not."""
        moment = _now(now)
        intention = await self._intentions.intention(intention_id, lock=True)
        if intention is None:
            return None
        plan = await self._latest(intention_id, lock=True)
        if plan is None or plan.status != "planned":
            raise PlanRefusedError("nothing_planned", "Nothing planned to start.")
        plan.timezone = timezone if _zone(timezone).key == timezone else "UTC"
        steps = await self._steps(plan.id)
        later = at is not None and at > moment
        failed = await self._check(plan, steps, at if later and at else moment)
        if failed:
            self._event(plan, "checks_failed", at=moment, by=by, detail={"failed": failed})
            await self._session.flush()
            raise PlanRefusedError(
                "checks_failed", "What must hold before it runs does not.", failed
            )
        service = IntentionService(self._intentions)
        if later and at:
            plan.status = "scheduled"
            plan.scheduled_for = at
            self._event(plan, "scheduled", at=moment, by=by, detail={"for": at.isoformat()})
            await service.move(
                intention_id,
                S.SCHEDULED,
                actor=Actor.PERSON,
                by=by,
                detail={"plan_id": str(plan.id), "for": at.isoformat()},
                now=moment,
            )
            await self._session.flush()
            return await self.read(plan, moment)
        await service.move(
            intention_id,
            S.EXECUTING,
            actor=Actor.PERSON,
            by=by,
            detail={"plan_id": str(plan.id), "number": plan.number},
            now=moment,
        )
        plan.status = "running"
        plan.started_at = moment
        plan.started_by = by
        self._event(plan, "started", at=moment, by=by)
        await self.advance(plan, now=moment)
        return await self.read(plan, moment)

    # running

    async def advance(
        self,
        plan: IntentionPlan,
        *,
        network: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        now: datetime | None = None,
    ) -> str:
        """The next steps, in order: a person's waits for them; a system's
        is called — by the job (`network`), queued otherwise. Finished, the
        intention moved. What it stopped at, returned."""
        steps = await self._steps(plan.id)
        for step in steps:
            if step.status in ("succeeded", "skipped", "cancelled"):
                continue
            if step.status in ("awaiting", "running"):
                return "waiting"
            if step.status == "failed":
                return await self._finish(plan, steps, failed=step, now=_now(now))
            # pending
            if plan.detail.get("cancel_requested"):
                return await self._finish(plan, steps, cancelled=True, now=_now(now))
            if step.executor == "manual":
                step.status = "awaiting"
                step.started_at = _now(now)
                self._event(plan, "awaiting_person", at=_now(now), step=step)
                await self._session.flush()
                return "waiting"
            if not network:
                if plan.id not in self.to_queue:
                    self.to_queue.append(plan.id)
                await self._session.flush()
                return "queued"
            await self._call(plan, step, transport=transport)
            if step.status == "awaiting":
                return "waiting"
            if step.status == "failed":
                return await self._finish(plan, steps, failed=step, now=_now(now))
        return await self._finish(plan, steps, now=_now(now))

    async def _call(
        self,
        plan: IntentionPlan,
        step: IntentionPlanStep,
        *,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        """The authorized system called, signed — checked again first: what
        was authorized when planned may not be any more."""
        started = _now(None)
        steps = await self._steps(plan.id)
        failed = [
            c
            for c in await self._check(plan, steps, started)
            if c["code"] in ("endpoint_allows", "approvers_allowed", "decision_approved")
        ]
        endpoint = (
            await self._session.get(ActionEndpoint, step.endpoint_id) if step.endpoint_id else None
        )
        if failed or endpoint is None:
            step.status = "failed"
            step.error = "no_longer_authorized"
            step.finished_at = started
            step.evidence = {"checks": failed}
            self._event(plan, "step_failed", at=started, step=step, detail={"error": step.error})
            await self._session.flush()
            return
        intention = await self._intentions.intention(plan.intention_id)
        payload = {
            "event": "leka.action",
            "delivery": str(step.id),
            "workspace": str(self._workspace_id),
            "intention": {
                "id": str(plan.intention_id),
                "title": intention.title if intention else None,
            },
            "decision": {"id": str(plan.decision_id), "revision": plan.revision},
            "plan": {"id": str(plan.id), "number": plan.number},
            "action": step.action,
            "targets": step.targets,
            "environment": step.environment,
            "constraints": step.constraints,
            "requested_at": started.isoformat(),
        }
        body = body_of(payload)
        signed_at = int(started.timestamp())
        step.status = "running"
        step.started_at = started
        self._event(plan, "step_started", at=started, step=step, detail={"endpoint": endpoint.name})
        await self._session.commit()
        secret = secret_box.decrypt(endpoint.secret_ciphertext)
        request = {
            "url": endpoint.url,
            "payload": payload,
            "sha256": hashlib.sha256(body).hexdigest(),
            "signed_at": signed_at,
        }
        began = clock.monotonic()
        outcome: Outcome
        response: dict[str, object] | None = None
        circuit = f"action_endpoint:{endpoint.id}"
        try:
            if not await breaker.allow(circuit):
                # Failing for a while: not called now — a person retries it.
                raise breaker.OpenCircuitError(circuit)
            async with httpx.AsyncClient(
                transport=transport or PublicTransport(), timeout=TIMEOUT
            ) as client:
                answered = await client.post(
                    endpoint.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "LEKA-Actions/1",
                        SIGNATURE: sign(secret, signed_at, body),
                        DELIVERY: str(step.id),
                    },
                )
            outcome = outcome_of(answered.status_code, answered.content)
            response = {
                "status": answered.status_code,
                "excerpt": excerpt(answered.content),
                "duration_ms": int((clock.monotonic() - began) * 1000),
            }
        except breaker.OpenCircuitError:
            outcome = Outcome("failed", reason="circuit_open")
        except BlockedAddressError:
            outcome = Outcome("failed", reason="blocked_address")
        except httpx.TimeoutException:
            # It may have acted, or not: a person finds out — never assumed.
            outcome = Outcome("failed", reason="no_answer")
            await breaker.failure(circuit)
        except httpx.HTTPError as error:
            outcome = Outcome("failed", reason=type(error).__name__)
            await breaker.failure(circuit)
        else:
            # A system that answers 5xx is failing; anything else, it is up.
            if response is not None and int(str(response["status"])) >= 500:
                await breaker.failure(circuit)
            else:
                await breaker.success(circuit)
        moment = _now(None)
        endpoint.last_called_at = moment
        step.evidence = {
            "request": request,
            "response": response,
            "outcome": {
                "status": outcome.status,
                "reason": outcome.reason,
                "detail": outcome.detail,
                "ref": outcome.ref,
                "metrics": dict(outcome.metrics),
            },
        }
        if outcome.status == "succeeded":
            step.status = "succeeded"
            step.finished_at = moment
            self._event(plan, "step_succeeded", at=moment, step=step)
        elif outcome.status == "awaiting":
            step.status = "awaiting"
            self._event(
                plan, "awaiting_confirmation", at=moment, step=step, detail={"ref": outcome.ref}
            )
        else:
            step.status = "failed"
            step.error = outcome.reason
            step.finished_at = moment
            self._event(plan, "step_failed", at=moment, step=step, detail={"error": outcome.reason})
        # LEKA called a system on the workspace's behalf (LEKA-407).
        audit(
            self._session,
            plan.workspace_id,
            "action",
            "action.executed",
            outcome="failure" if outcome.status == "failed" else "success",
            target=Target("action_endpoint", endpoint.id, endpoint.name),
            detail={
                "action": step.action,
                "environment": step.environment,
                "plan": str(plan.id),
                "intention": str(plan.intention_id),
                "status": outcome.status,
                **({"reason": outcome.reason} if outcome.reason else {}),
                **({"http": response["status"]} if response else {}),
            },
            at=moment,
        )
        await self._session.flush()

    async def _finish(
        self,
        plan: IntentionPlan,
        steps: Sequence[IntentionPlanStep],
        *,
        failed: IntentionPlanStep | None = None,
        cancelled: bool = False,
        now: datetime,
    ) -> str:
        """Done: every step succeeded — verifying; one failed or cancelled —
        the rest not run, the intention failed. Nothing said done that was
        not."""
        for step in steps:
            if step.status == "pending":
                step.status = "cancelled" if cancelled else "skipped"
        service = IntentionService(self._intentions)
        detail = {"plan_id": str(plan.id), "number": plan.number}
        plan.finished_at = now
        if failed is None and not cancelled:
            plan.status = "succeeded"
            self._event(plan, "succeeded", at=now)
            await service.move(
                plan.intention_id, S.VERIFYING, actor=Actor.SYSTEM, detail=detail, now=now
            )
            # Whether it achieved what was expected (LEKA-392).
            await VerificationService(self._session, self._workspace_id).open(plan, now=now)
            await self._session.flush()
            return "succeeded"
        plan.status = "cancelled" if cancelled else "failed"
        plan.error = "cancelled" if cancelled else (failed.error if failed else None)
        self._event(plan, plan.status, at=now, detail={"error": plan.error})
        await service.move(
            plan.intention_id,
            S.FAILED,
            actor=Actor.SYSTEM,
            reason="Cancelled while running." if cancelled else "An action did not succeed.",
            detail={**detail, "error": plan.error, "step": failed.position if failed else None},
            now=now,
        )
        await self._session.flush()
        return plan.status

    # a person's word

    async def report(
        self,
        intention_id: uuid.UUID,
        step_id: uuid.UUID,
        *,
        outcome: str,
        note: str,
        link: str | None,
        by: uuid.UUID,
        now: datetime | None = None,
    ) -> IntentionPlanRead | None:
        """A step waiting on a person — theirs, or a system's that accepted
        the work — said done or failed, with what shows it; the plan goes
        on."""
        moment = _now(now)
        intention = await self._intentions.intention(intention_id, lock=True)
        if intention is None:
            return None
        plan = await self._latest(intention_id, lock=True)
        step = await self._session.get(IntentionPlanStep, step_id)
        if plan is None or step is None or step.plan_id != plan.id:
            return None
        if plan.status != "running" or step.status != "awaiting":
            raise PlanRefusedError("not_awaiting", "This step is not waiting for anyone.")
        step.status = "succeeded" if outcome == "succeeded" else "failed"
        step.finished_at = moment
        step.error = None if outcome == "succeeded" else "reported_failed"
        step.evidence = {
            **step.evidence,
            "reported": {"by": str(by), "at": moment.isoformat(), "note": note, "link": link},
        }
        self._event(
            plan,
            "step_succeeded" if outcome == "succeeded" else "step_failed",
            at=moment,
            by=by,
            step=step,
            detail={"note": note, "link": link},
        )
        await self.advance(plan, now=moment)
        return await self.read(plan, moment)

    # stopping

    async def cancel(
        self, intention_id: uuid.UUID, *, by: uuid.UUID, reason: str, now: datetime | None = None
    ) -> IntentionPlanRead | None:
        """Before it runs: the plan cancelled, the intention approved again.
        While it runs: what has not started cancelled — what is running ends
        and is said — the intention failed."""
        moment = _now(now)
        intention = await self._intentions.intention(intention_id, lock=True)
        if intention is None:
            return None
        plan = await self._latest(intention_id, lock=True)
        if plan is None or plan.status not in ACTIVE:
            raise PlanRefusedError("not_cancellable", "Nothing on its way to cancel.")
        self._event(plan, "cancel_requested", at=moment, by=by, detail={"reason": reason})
        if plan.status in ("planned", "scheduled"):
            was = plan.status
            plan.status = "cancelled"
            plan.finished_at = moment
            plan.error = "cancelled"
            for step in await self._steps(plan.id):
                step.status = "cancelled"
            if was == "scheduled":
                await IntentionService(self._intentions).move(
                    intention_id,
                    S.APPROVED,
                    actor=Actor.PERSON,
                    by=by,
                    reason=reason,
                    detail={"plan_id": str(plan.id)},
                    now=moment,
                )
            await self._session.flush()
            return await self.read(plan, moment)
        plan.detail = {**plan.detail, "cancel_requested": True, "cancelled_by": str(by)}
        steps = await self._steps(plan.id)
        for step in steps:
            if step.status in ("pending", "awaiting"):
                step.status = "cancelled"
                step.finished_at = moment
        if not any(s.status == "running" for s in steps):
            await self._finish(plan, steps, cancelled=True, now=moment)
        await self._session.flush()
        return await self.read(plan, moment)


# ── the jobs ────────────────────────────────────────────────────────────────


async def queue_plan(workspace_id: uuid.UUID, plan_id: uuid.UUID) -> bool:
    """The job that calls the systems of a plan; False when one is already
    queued or running."""
    run = await enqueue_job(
        PLAN_JOB,
        str(workspace_id),
        str(plan_id),
        for_workspace_id=workspace_id,
        concurrency_key=concurrency_key(plan_id),
    )
    return run is not None


async def execute_plan(
    workspace_id: uuid.UUID,
    plan_id: uuid.UUID,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """A plan run as far as it goes: its systems called, what waits on a
    person left waiting."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            plan = await session.scalar(
                select(IntentionPlan).where(IntentionPlan.id == plan_id).with_for_update()
            )
            if plan is None or plan.status != "running":
                return "not_running"
            went = await ActionService(session, workspace_id).advance(
                plan, network=True, transport=transport
            )
            await session.commit()
    logger.info("intention_plan_advanced", plan=str(plan_id), went=went)
    return went


def run_plan(workspace_id: str, plan_id: str) -> str:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(execute_plan(uuid.UUID(workspace_id), uuid.UUID(plan_id)))


async def start_due(*, now: datetime | None = None) -> dict[str, int]:
    """The plans scheduled for now or before, checked again and run — or
    failed, said why, when what must hold no longer does."""
    moment = _now(now)
    with system_scope():
        async with session_factory() as session:
            due = (
                (
                    await session.execute(
                        select(IntentionPlan.workspace_id, IntentionPlan.id).where(
                            IntentionPlan.status == "scheduled",
                            IntentionPlan.scheduled_for <= moment,
                        )
                    )
                )
                .tuples()
                .all()
            )
    counts = {"started": 0, "blocked": 0}
    for workspace_id, plan_id in due:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                service = ActionService(session, workspace_id)
                plan = await session.scalar(
                    select(IntentionPlan).where(IntentionPlan.id == plan_id).with_for_update()
                )
                if plan is None or plan.status != "scheduled":
                    continue
                steps = await service._steps(plan.id)
                failed = await service._check(plan, steps, moment)
                intentions = IntentionService(IntentionRepository(session, workspace_id))
                await intentions.move(
                    plan.intention_id,
                    S.EXECUTING,
                    actor=Actor.SYSTEM,
                    detail={"plan_id": str(plan.id), "scheduled": True},
                    now=moment,
                )
                plan.status = "running"
                plan.started_at = moment
                if failed:
                    plan.status = "blocked"
                    plan.finished_at = moment
                    plan.error = "checks_failed"
                    for step in steps:
                        step.status = "cancelled"
                    service._event(plan, "checks_failed", at=moment, detail={"failed": failed})
                    await intentions.move(
                        plan.intention_id,
                        S.FAILED,
                        actor=Actor.SYSTEM,
                        reason="What had to hold at its time no longer did.",
                        detail={"plan_id": str(plan.id), "failed": [f["code"] for f in failed]},
                        now=moment,
                    )
                    counts["blocked"] += 1
                else:
                    service._event(plan, "started", at=moment)
                    went = await service.advance(plan, now=moment)
                    counts["started"] += 1
                    await session.commit()
                    if went == "queued":
                        await queue_plan(workspace_id, plan.id)
                    continue
                await session.commit()
    logger.info("intention_plans_due", **counts)
    return counts


def run_due_plans() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(start_due())
