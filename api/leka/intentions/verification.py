"""Whether what ran achieved what was expected (LEKA-392): expectations set
before it runs, a verification opened once it succeeded, read again from the
company model — and what the systems that acted reported — until met or the
deadline, concluded, the intention moved, the company's context told.

    planned ──▶ expected()       LEKA's defaults: healthy after what heals,
                                 the incidents open on it resolved — changed
                                 by who may approve, before it runs
    succeeded ─▶ open()          observed after it settled, until its deadline
              ──▶ observe()      each expectation met, not met, unknown,
                                 awaiting a person; all met: concluded
              ──▶ report()       a person's word on one, with what shows it
              ──▶ conclude()     at the deadline, or by a person: succeeded,
                                 partial, failed
    concluded ─▶ the intention completed ("verified") — or failed, its
                 outcome said; succeeded, the model built again from its
                 sources (an operation of the model's course, LEKA-383,
                 whose reason names the intention) and the outcome linked
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.db import session_factory, system_scope, workspace_scope
from leka.intentions.lifecycle import Actor, IntentionStatus
from leka.intentions.models import (
    IntentionPlan,
    IntentionPlanEvent,
    IntentionPlanStep,
    IntentionVerification,
)
from leka.intentions.outcome import (
    OPEN,
    SETTLE,
    WINDOW,
    Expectation,
    ExpectationError,
    Observed,
    Result,
    Seen,
    Thing,
    expected_for,
    observe,
    reported,
    validated,
    verdict,
)
from leka.intentions.repository import IntentionRepository
from leka.intentions.schemas import IntentionVerificationRead
from leka.intentions.service import IntentionService
from leka.knowledge import (
    AssertionRepository,
    Entity,
    EvolutionRepository,
    EvolutionService,
    Relationship,
    queue_model_build,
)

logger = structlog.get_logger(__name__)

S = IntentionStatus
DONE = ("succeeded", "partial", "failed")


class VerificationRefusedError(Exception):
    """What cannot be done to its expectations or its verification now."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def verification_read(row: IntentionVerification) -> IntentionVerificationRead:
    return IntentionVerificationRead.model_validate(row, from_attributes=True)


async def open_incidents_on(
    session: AsyncSession, workspace_id: uuid.UUID, targets: Sequence[uuid.UUID]
) -> dict[str, list[str]]:
    """The incidents open on each thing, now: what affects it, not resolved."""
    if not targets:
        return {}
    rows = await session.execute(
        select(Relationship.to_entity_id, Entity.id)
        .join(Entity, Entity.id == Relationship.from_entity_id)
        .where(
            Relationship.workspace_id == workspace_id,
            Relationship.type == "affects",
            Relationship.to_entity_id.in_(targets),
            Entity.type == "incident",
            Entity.attributes["state"].astext.in_(sorted(OPEN)),
        )
    )
    found: dict[str, list[str]] = {}
    for target, incident in rows.tuples():
        found.setdefault(str(target), []).append(str(incident))
    return found


async def expected(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    steps: Sequence[tuple[str, Sequence[Mapping[str, object]]]],
) -> list[dict[str, object]]:
    """LEKA's default expectations for these steps — each its action and
    what it acts on."""
    targets = {uuid.UUID(str(t["id"])) for _, things in steps for t in things}
    incidents = await open_incidents_on(session, workspace_id, sorted(targets))
    shaped = [{"action": action, "targets": list(things)} for action, things in steps]
    return [e.as_dict() for e in expected_for(shaped, incidents)]


class VerificationService:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._intentions = IntentionRepository(session, workspace_id)
        # Whether a concluded success asked for the model to be built again:
        # the caller queues it once it has committed.
        self.build = False

    # reading

    async def _latest_plan(
        self, intention_id: uuid.UUID, *, lock: bool = False
    ) -> IntentionPlan | None:
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

    async def verifications(
        self, intention_id: uuid.UUID
    ) -> list[IntentionVerificationRead] | None:
        if await self._intentions.intention(intention_id) is None:
            return None
        rows = await self._session.scalars(
            select(IntentionVerification)
            .where(IntentionVerification.intention_id == intention_id)
            .order_by(IntentionVerification.created_at.desc())
        )
        return [verification_read(r) for r in rows]

    async def _current(
        self, intention_id: uuid.UUID, *, lock: bool = False
    ) -> IntentionVerification | None:
        query = (
            select(IntentionVerification)
            .where(IntentionVerification.intention_id == intention_id)
            .order_by(IntentionVerification.created_at.desc())
            .limit(1)
        )
        found: IntentionVerification | None = await self._session.scalar(
            query.with_for_update() if lock else query
        )
        return found

    def _event(
        self,
        plan_id: uuid.UUID,
        kind: str,
        *,
        at: datetime,
        by: uuid.UUID | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self._session.add(
            IntentionPlanEvent(
                workspace_id=self._workspace_id,
                id=uuid.uuid4(),
                plan_id=plan_id,
                kind=kind,
                actor=Actor.PERSON if by else Actor.SYSTEM,
                by=by,
                at=at,
                detail=dict(detail or {}),
            )
        )

    # expecting

    async def set_expectations(
        self,
        intention_id: uuid.UUID,
        items: Sequence[Mapping[str, object]],
        *,
        by: uuid.UUID,
        now: datetime | None = None,
    ) -> list[dict[str, object]] | None:
        """What should be true once it ran — before it runs. Refused once
        the plan started, or when one cannot be checked as said."""
        intention = await self._intentions.intention(intention_id, lock=True)
        if intention is None:
            return None
        plan = await self._latest_plan(intention_id, lock=True)
        if plan is None or plan.status != "planned":
            raise VerificationRefusedError(
                "not_planned", "Expectations are set before it runs, on a plan ready to run."
            )
        try:
            kept = [validated(Expectation.from_dict(item)).as_dict() for item in items]
        except (ExpectationError, KeyError) as error:
            raise VerificationRefusedError("invalid_expectation", str(error)) from error
        ids = [str(k["id"]) for k in kept]
        if len(ids) != len(set(ids)):
            raise VerificationRefusedError("invalid_expectation", "Two expectations share an id.")
        plan.expectations = kept
        self._event(plan.id, "expectations_set", at=_now(now), by=by, detail={"count": len(kept)})
        await self._session.flush()
        return kept

    # verifying

    async def open(
        self, plan: IntentionPlan, *, now: datetime | None = None
    ) -> IntentionVerification:
        """Its verification, once it succeeded: observed after it settled,
        until its deadline."""
        moment = _now(now)
        row = IntentionVerification(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            intention_id=plan.intention_id,
            plan_id=plan.id,
            status="verifying",
            expectations=list(plan.expectations),
            results=[],
            observe_after=moment + SETTLE,
            deadline=moment + WINDOW,
            context_update={},
            detail={},
            created_at=moment,
        )
        self._session.add(row)
        self._event(
            plan.id,
            "verification_started",
            at=moment,
            detail={"expectations": len(plan.expectations), "deadline": row.deadline.isoformat()},
        )
        await self._session.flush()
        return row

    async def _observed(self, row: IntentionVerification) -> Observed:
        expectations = [Expectation.from_dict(e) for e in row.expectations]
        ids: set[uuid.UUID] = set()
        targets: set[uuid.UUID] = set()
        for e in expectations:
            if e.target and "id" in e.target:
                targets.add(uuid.UUID(e.target["id"]))
            ids.update(uuid.UUID(i) for i in e.incidents)
        ids |= targets
        incidents = await open_incidents_on(self._session, self._workspace_id, sorted(targets))
        things: dict[str, Thing] = {}
        if ids:
            rows = await self._session.execute(
                select(
                    Entity.id, Entity.type, Entity.lifecycle, Entity.attributes, Entity.last_seen_at
                ).where(Entity.workspace_id == self._workspace_id, Entity.id.in_(sorted(ids)))
            )
            for entity_id, kind, lifecycle, attributes, seen_at in rows.tuples():
                things[str(entity_id)] = Thing(
                    type=str(getattr(kind, "value", kind)),
                    lifecycle=str(getattr(lifecycle, "value", lifecycle)),
                    attributes=dict(attributes or {}),
                    open_incidents=tuple(incidents.get(str(entity_id), ())),
                    seen_at=seen_at,
                )
        metrics: dict[str, object] = {}
        steps = await self._session.scalars(
            select(IntentionPlanStep)
            .where(IntentionPlanStep.plan_id == row.plan_id)
            .order_by(IntentionPlanStep.position)
        )
        for step in steps:
            outcome = (step.evidence or {}).get("outcome")
            if isinstance(outcome, Mapping):
                metrics.update(dict(outcome.get("metrics") or {}))
        # Whether the model holds incidents at all: only then does none
        # open on a thing say it is healthy.
        known = await self._session.scalar(
            select(
                exists().where(Entity.workspace_id == self._workspace_id, Entity.type == "incident")
            )
        )
        return Observed(
            things=things, metrics=metrics, incidents_known=bool(known), since=row.created_at
        )

    async def observe(
        self,
        row: IntentionVerification,
        *,
        now: datetime | None = None,
        final: bool | None = None,
        by: uuid.UUID | None = None,
        note: str | None = None,
    ) -> str:
        """Every expectation read again; concluded when all are met — or,
        `final` (the deadline, or a person), with what was observed."""
        moment = _now(now)
        expectations = [Expectation.from_dict(e) for e in row.expectations]
        earlier = {str(r["expectation_id"]): Result.from_dict(r) for r in row.results}
        results = observe(expectations, await self._observed(row), earlier)
        row.results = [r.as_dict() for r in results]
        row.observed_at = moment
        ends = final if final is not None else moment >= row.deadline
        status = verdict(results, final=ends)
        if status != "verifying":
            await self._conclude(row, status, by=by, note=note, now=moment)
        await self._session.flush()
        return status

    async def _conclude(
        self,
        row: IntentionVerification,
        status: str,
        *,
        by: uuid.UUID | None,
        note: str | None,
        now: datetime,
    ) -> None:
        """Concluded: the intention completed or failed, its outcome said;
        succeeded, the company's model built again from its sources, the
        outcome linked."""
        row.status = status
        row.concluded_at = now
        row.concluded_by = by
        if note:
            row.detail = {**row.detail, "note": note}
        met = sum(1 for r in row.results if r.get("seen") == "met")
        detail = {
            "verification_id": str(row.id),
            "plan_id": str(row.plan_id),
            "outcome": status,
            "met": met,
            "expected": len(row.results),
        }
        self._event(row.plan_id, f"verification_{status}", at=now, by=by, detail=detail)
        actor = Actor.PERSON if by else Actor.SYSTEM
        service = IntentionService(self._intentions)
        intention = await self._intentions.intention(row.intention_id)
        # Linked first: its story ends on the verdict.
        await service.link(
            row.intention_id,
            "outcome",
            row.id,
            actor=Actor.SYSTEM,
            label=status,
            detail={"met": met, "expected": len(row.results)},
            now=now,
        )
        if status == "succeeded":
            evolution = EvolutionService(
                EvolutionRepository(self._session, self._workspace_id),
                AssertionRepository(self._session, self._workspace_id),
            )
            title = intention.title if intention else str(row.intention_id)
            operation = await evolution.rebuild(
                reason=f"After « {title[:200]} »: its outcome verified (LEKA-392).",
                by=by,
                now=now,
            )
            # A rebuild already queued is the one: its reason says whose.
            row.context_update = {
                "operation_id": str(operation.id),
                "kind": "rebuild",
                "reason": operation.reason,
                "at": now.isoformat(),
            }
            self.build = True
            await service.move(
                row.intention_id,
                S.COMPLETED,
                actor=actor,
                by=by,
                reason=note,
                detail=detail,
                now=now,
            )
        else:
            await service.move(
                row.intention_id,
                S.FAILED,
                actor=actor,
                by=by,
                reason=note
                or (
                    "Only part of what was expected came."
                    if status == "partial"
                    else "What was expected did not come."
                ),
                detail=detail,
                now=now,
            )

    async def report(
        self,
        intention_id: uuid.UUID,
        expectation_id: str,
        *,
        met: bool,
        note: str,
        link: str | None,
        by: uuid.UUID,
        now: datetime | None = None,
    ) -> IntentionVerificationRead | None:
        """A person's word on one expectation, with what shows it; concluded
        when it was the last one missing."""
        moment = _now(now)
        if await self._intentions.intention(intention_id, lock=True) is None:
            return None
        row = await self._current(intention_id, lock=True)
        if row is None or row.status != "verifying":
            raise VerificationRefusedError("not_verifying", "Nothing is being verified.")
        found = {str(r["expectation_id"]): Result.from_dict(r) for r in row.results}
        if expectation_id not in {str(e["id"]) for e in row.expectations}:
            return None
        before = found.get(expectation_id) or Result(expectation_id, Seen.AWAITING)
        found[expectation_id] = reported(
            before, met=met, note=note, link=link, by=str(by), at=moment.isoformat()
        )
        row.results = [
            found.get(str(e["id"]), Result(str(e["id"]), Seen.AWAITING)).as_dict()
            for e in row.expectations
        ]
        self._event(
            row.plan_id,
            "expectation_reported",
            at=moment,
            by=by,
            detail={"expectation": expectation_id, "met": met, "note": note},
        )
        await self.observe(row, now=moment, final=False, by=by)
        return verification_read(row)

    async def conclude(
        self, intention_id: uuid.UUID, *, by: uuid.UUID, note: str, now: datetime | None = None
    ) -> IntentionVerificationRead | None:
        """Concluded now by a person, with what is observed: what is not met
        yet counts as not met."""
        if await self._intentions.intention(intention_id, lock=True) is None:
            return None
        row = await self._current(intention_id, lock=True)
        if row is None or row.status != "verifying":
            raise VerificationRefusedError("not_verifying", "Nothing is being verified.")
        await self.observe(row, now=_now(now), final=True, by=by, note=note)
        return verification_read(row)

    async def check_now(
        self, intention_id: uuid.UUID, *, now: datetime | None = None
    ) -> IntentionVerificationRead | None:
        """Read again now, without waiting for the sweep."""
        if await self._intentions.intention(intention_id, lock=True) is None:
            return None
        row = await self._current(intention_id, lock=True)
        if row is None or row.status != "verifying":
            raise VerificationRefusedError("not_verifying", "Nothing is being verified.")
        await self.observe(row, now=_now(now), final=False)
        return verification_read(row)


# ── the sweep ───────────────────────────────────────────────────────────────


async def verify_due(*, now: datetime | None = None) -> dict[str, int]:
    """Every verification past its settling time read again — concluded at
    its deadline."""
    moment = _now(now)
    with system_scope():
        async with session_factory() as session:
            due = (
                (
                    await session.execute(
                        select(IntentionVerification.workspace_id, IntentionVerification.id).where(
                            IntentionVerification.status == "verifying",
                            IntentionVerification.observe_after <= moment,
                        )
                    )
                )
                .tuples()
                .all()
            )
    counts = {"observed": 0, "concluded": 0}
    for workspace_id, verification_id in due:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                service = VerificationService(session, workspace_id)
                row = await session.scalar(
                    select(IntentionVerification)
                    .where(IntentionVerification.id == verification_id)
                    .with_for_update()
                )
                if row is None or row.status != "verifying":
                    continue
                status = await service.observe(row, now=moment)
                await session.commit()
                counts["observed"] += 1
                if status in DONE:
                    counts["concluded"] += 1
                if service.build:
                    await queue_model_build(workspace_id)
    logger.info("intention_verifications_observed", **counts)
    return counts


def run_due_verifications() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(verify_due())
