"""The Décision and Action steps carried by LEKA's agents (2026-10-14, the
product call: every request goes through its five steps; an agent is never
started without a person seeing and validating it; nothing stays « en
cours » for ever; a file announced is delivered, or its error said).

    Décision   launch(): the agents its analysis proposed (proposal.py)
               that a person chose — each checked usable here, its inputs
               whole, the credits there — started on the intention, the
               files asked for and none other; the intention approved,
               then executing. Or by_hand(): its asker does it, the plan in
               hand — the intention done.
    Action     settle(): once every agent launched has ended — the
               intention verified (each delivered what it said), or failed
               (which agent, why). retry(): the agents that failed, launched
               again with what they were given.

Settled when its page is read (the route) and by the sweep: an intention
nobody looks at is never left executing.

An intention that asks to change systems keeps its own decision (LEKA-390):
agents launched beside it leave that decision open.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing import AddOnCheckout
from leka.capabilities import (
    AgentRun,
    AgentRuntime,
    CatalogueService,
    RunRefusedError,
    permitted,
    queue_run,
)
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import Actor as AIActor
from leka.governance import AIControlService, ai_event, holding
from leka.intentions.decisions import DecisionStatus
from leka.intentions.journey import AGENTS, SELF
from leka.intentions.lifecycle import Actor, IllegalTransitionError, IntentionStatus, move
from leka.intentions.models import Intention, IntentionAnalysis, IntentionDecision, IntentionEvent
from leka.intentions.proposal import CHOSEN, inputs_of
from leka.intentions.repository import IntentionRepository
from leka.intentions.schemas import AgentProposalRead
from leka.intentions.service import (
    IntentionArchivedError,
    IntentionService,
    NotYoursError,
    _yours,
)
from leka.platform import MembershipRepository

logger = structlog.get_logger(__name__)

S = IntentionStatus
# A run not ended yet: queued, running, or held for an approval (LEKA-406).
MOVING = frozenset({"queued", "running", "awaiting_approval"})
LAUNCHED = ("execution_started", "retried")


class AgentsRefusedError(Exception):
    """Why its agents cannot be launched — said by its code, what is in the
    way in `detail`; nothing started."""

    def __init__(self, code: str, **detail: object) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Chosen:
    """An agent a person launches: its inputs as they completed them, the
    files they want drawn."""

    key: str
    inputs: Mapping[str, object] = field(default_factory=dict)
    formats: Sequence[str] = ()
    # The only sources it reads; none: the intention's own, else every one.
    sources: Sequence[uuid.UUID] = ()


async def proposal_of(session: AsyncSession, intention: Intention) -> AgentProposalRead | None:
    """What its latest analysis of this version proposed."""
    row = await session.scalar(
        select(IntentionAnalysis)
        .where(
            IntentionAnalysis.workspace_id == intention.workspace_id,
            IntentionAnalysis.intention_id == intention.id,
            IntentionAnalysis.result.is_not(None),
        )
        .order_by(IntentionAnalysis.number.desc())
        .limit(1)
    )
    said = (row.result or {}).get("proposal") if row is not None else None
    return AgentProposalRead.model_validate(said) if said else None


async def _decision_open(session: AsyncSession, intention: Intention) -> bool:
    """Whether its decision on actions to systems (LEKA-390) waits."""
    found = await session.scalar(
        select(IntentionDecision.id)
        .where(
            IntentionDecision.workspace_id == intention.workspace_id,
            IntentionDecision.intention_id == intention.id,
            IntentionDecision.status.in_(
                (DecisionStatus.PROPOSED.value, DecisionStatus.CHANGES_REQUESTED.value)
            ),
        )
        .limit(1)
    )
    return found is not None


async def _short(session: AsyncSession, workspace_id: uuid.UUID, keys: Sequence[str]) -> bool:
    """Whether this month's credits are short of what these agents have cost
    here: never started to be stopped midway (LEKA-439)."""
    # Looked up when used: feasibility's own imports reach back here.
    from leka.intentions.feasibility import credits_left, run_costs

    now = datetime.now(UTC)
    month = await credits_left(session, workspace_id, now=now)
    if not month.enforced:
        return False
    costs = await run_costs(session, keys, now=now)
    return month.state == "exhausted" or month.remaining < sum(costs.values())


async def _start(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention: Intention,
    chosen: Sequence[Chosen],
    *,
    by: uuid.UUID,
) -> list[AgentRun]:
    """Each checked, then all started — or none, AgentsRefusedError saying
    why."""
    permissions = await permitted(session, workspace_id, by)
    catalogue = CatalogueService(session, workspace_id)
    # Asked on some sources only: its agents read those, unless told others.
    asked_on = [uuid.UUID(str(x)) for x in _list(intention.scope, "sources")]
    checked: list[tuple[str, dict[str, object], list[str], str, list[uuid.UUID]]] = []
    for each in chosen:
        entry = await catalogue.entry(each.key, permissions=permissions, user_id=by)
        if entry is None:
            raise AgentsRefusedError("unknown_agent", agent=each.key)
        if not entry.availability.available:
            raise AgentsRefusedError(
                "unavailable", agent=each.key, reasons=list(entry.availability.codes)
            )
        inputs, missing = inputs_of(entry, each.inputs)
        if missing:
            raise AgentsRefusedError("missing_inputs", agent=each.key, missing=missing)
        formats = [f for f in each.formats if f in CHOSEN]
        checked.append(
            (each.key, inputs, formats, entry.definition.risk, list(each.sources) or asked_on)
        )
    if await _short(session, workspace_id, [c[0] for c in checked]):
        raise AgentsRefusedError("credits")
    seat = await MembershipRepository(session, workspace_id).get_for_user(by)
    actor = AIActor(user_id=by, roles=frozenset({seat.role.value})) if seat else None
    controls = await AIControlService(session, workspace_id).active()
    runtime = AgentRuntime(session, workspace_id)
    started: list[AgentRun] = []
    for key, inputs, formats, risk, sources in checked:
        held = holding(controls, key, risk, actor)
        try:
            run = await runtime.start(
                key,
                inputs,
                by=by,
                permissions=permissions,
                intention_id=intention.id,
                context_id=intention.context_id,
                held_by=held.name if held is not None else None,
                formats=formats,
                sources=sources,
            )
        except RunRefusedError as error:
            raise AgentsRefusedError("refused", agent=key, why=str(error)) from error
        if held is not None:
            ai_event(
                session,
                workspace_id,
                held,
                "held",
                actor=actor,
                purpose=f"agent:{run.key}",
                ref=run.key,
                run_id=run.id,
                detail={"risk": risk, "intention_id": str(intention.id)},
            )
        started.append(run)
    return started


async def launch(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    chosen: Sequence[Chosen],
    *,
    by: uuid.UUID,
    steward: bool = False,
    now: datetime | None = None,
) -> tuple[Intention, list[AgentRun]] | None:
    """The agents a person chose, started on the intention: approved, then
    executing. The caller commits, then queues each run not held."""
    repository = IntentionRepository(session, workspace_id)
    intention = await repository.intention(intention_id, lock=True)
    if intention is None:
        return None
    _yours(intention, by, steward)
    if intention.archived_at is not None:
        raise IntentionArchivedError
    if not chosen:
        raise AgentsRefusedError("nothing_chosen")
    keys = [c.key for c in chosen]
    if len(set(keys)) != len(keys):
        raise AgentsRefusedError("twice")
    proposed = await proposal_of(session, intention)
    offered = {a.key for a in proposed.agents} if proposed is not None else set()
    outside = [k for k in keys if k not in offered]
    if outside:
        raise AgentsRefusedError("not_proposed", agents=outside)
    moment = now or datetime.now(UTC)
    status = S(intention.status)
    # Beside a decision on actions to systems, its agents leave it open.
    beside = status == S.AWAITING_DECISION and await _decision_open(session, intention)
    if not beside:
        # Refused before anything starts: a state that cannot be decided.
        move(status, S.APPROVED, Actor.PERSON)
    runs = await _start(session, workspace_id, intention, chosen, by=by)
    if not beside:
        service = IntentionService(repository)
        await service.move(
            intention.id,
            S.APPROVED,
            actor=Actor.PERSON,
            by=by,
            detail={"path": AGENTS, "agents": keys},
            now=moment,
        )
        await service.move(
            intention.id,
            S.EXECUTING,
            actor=Actor.SYSTEM,
            detail={"path": AGENTS, "runs": [str(r.id) for r in runs]},
            now=moment,
        )
    logger.info("intention_agents_launched", intention=str(intention.id), agents=keys)
    return intention, runs


async def by_hand(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    *,
    by: uuid.UUID,
    steward: bool = False,
    now: datetime | None = None,
) -> Intention | None:
    """Done by its asker, the plan in hand: nothing for LEKA to run."""
    repository = IntentionRepository(session, workspace_id)
    intention = await repository.intention(intention_id, lock=True)
    if intention is None:
        return None
    _yours(intention, by, steward)
    if intention.archived_at is not None:
        raise IntentionArchivedError
    return await IntentionService(repository).move(
        intention.id,
        S.COMPLETED,
        actor=Actor.PERSON,
        by=by,
        detail={"path": SELF},
        now=now,
    )


async def _launched(session: AsyncSession, intention: Intention) -> list[uuid.UUID]:
    """The runs its last launch started — or retried."""
    found = await session.scalar(
        select(IntentionEvent)
        .where(
            IntentionEvent.workspace_id == intention.workspace_id,
            IntentionEvent.intention_id == intention.id,
            IntentionEvent.kind == "moved",
            IntentionEvent.to_status == S.EXECUTING.value,
        )
        .order_by(IntentionEvent.sequence.desc())
        .limit(1)
    )
    detail: Mapping[str, Any] = (found.detail or {}) if found is not None else {}
    if found is None or detail.get("path") != AGENTS:
        return []
    return [uuid.UUID(str(r)) for r in _list(detail, "runs")]


def _list(detail: Mapping[str, Any] | None, key: str) -> list[Any]:
    found = (detail or {}).get(key)
    return list(found) if isinstance(found, list) else []


async def _runs(
    session: AsyncSession, intention: Intention, ids: Sequence[uuid.UUID]
) -> list[AgentRun]:
    if not ids:
        return []
    return list(
        (
            await session.scalars(
                select(AgentRun).where(
                    AgentRun.workspace_id == intention.workspace_id, AgentRun.id.in_(list(ids))
                )
            )
        ).all()
    )


async def settle(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> bool:
    """Once every agent launched has ended: verified, or failed. True when
    it moved; the caller commits."""
    repository = IntentionRepository(session, workspace_id)
    intention = await repository.intention(intention_id, lock=True)
    if intention is None or intention.status != S.EXECUTING.value:
        return False
    ids = await _launched(session, intention)
    if not ids:
        return False
    runs = await _runs(session, intention, ids)
    if len(runs) < len(ids) or any(r.status in MOVING for r in runs):
        return False
    moment = now or datetime.now(UTC)
    service = IntentionService(repository)
    failed = [r for r in runs if r.status != "succeeded"]
    if failed:
        first = failed[0]
        await service.move(
            intention.id,
            S.FAILED,
            actor=Actor.SYSTEM,
            reason="An agent did not deliver.",
            detail={
                "path": AGENTS,
                "runs": [str(r.id) for r in failed],
                "agent": first.key,
                "error": first.error or first.status,
            },
            now=moment,
        )
        logger.info("intention_agents_failed", intention=str(intention.id), agent=first.key)
        return True
    delivered = [
        {
            "agent": r.key,
            "run_id": str(r.id),
            "files": [
                f.get("format") for f in _list(r.detail, "deliverables") if isinstance(f, dict)
            ],
        }
        for r in runs
    ]
    await service.move(
        intention.id,
        S.VERIFYING,
        actor=Actor.SYSTEM,
        detail={"path": AGENTS, "runs": [str(r.id) for r in runs]},
        now=moment,
    )
    await service.move(
        intention.id,
        S.COMPLETED,
        actor=Actor.SYSTEM,
        reason="Every agent delivered.",
        detail={"path": AGENTS, "delivered": delivered},
        now=moment,
    )
    logger.info("intention_agents_delivered", intention=str(intention.id), runs=len(runs))
    return True


async def retry(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    *,
    by: uuid.UUID,
    steward: bool = False,
    now: datetime | None = None,
) -> tuple[Intention, list[AgentRun]] | None:
    """The agents that failed, launched again with what they were given;
    those that delivered kept. The caller commits, then queues."""
    repository = IntentionRepository(session, workspace_id)
    intention = await repository.intention(intention_id, lock=True)
    if intention is None:
        return None
    _yours(intention, by, steward)
    if intention.archived_at is not None:
        raise IntentionArchivedError
    move(S(intention.status), S.EXECUTING, Actor.PERSON)
    runs = await _runs(session, intention, await _launched(session, intention))
    failed = [r for r in runs if r.status != "succeeded"]
    if not failed:
        raise AgentsRefusedError("nothing_failed")
    again = await _start(
        session,
        workspace_id,
        intention,
        [
            Chosen(
                r.key,
                dict(r.inputs),
                [str(f) for f in _list(r.detail, "formats")],
                [uuid.UUID(str(x)) for x in _list(r.detail, "sources")],
            )
            for r in failed
        ],
        by=by,
    )
    kept = [r for r in runs if r.status == "succeeded"]
    await IntentionService(repository).move(
        intention.id,
        S.EXECUTING,
        actor=Actor.PERSON,
        by=by,
        detail={"path": AGENTS, "runs": [str(r.id) for r in [*kept, *again]]},
        now=now,
    )
    return intention, again


async def queue_all(workspace_id: uuid.UUID, runs: Sequence[AgentRun]) -> None:
    """Each run not held, for a worker — once committed."""
    for run in runs:
        if run.status == "queued":
            await queue_run(workspace_id, run.id)


async def settle_executing(*, limit: int = 100) -> int:
    """The sweep: every intention its agents work on, settled once they
    ended — none left executing because nobody looked."""
    with system_scope():
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(Intention.workspace_id, Intention.id)
                    .where(Intention.status == S.EXECUTING.value)
                    .limit(limit)
                )
            ).all()
    moved = 0
    for workspace_id, intention_id in rows:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                if await settle(session, workspace_id, intention_id):
                    await session.commit()
                    moved += 1
    if moved:
        logger.info("intention_agents_settled", moved=moved)
    return moved


async def launch_bought(workspace_id: uuid.UUID, checkout_id: uuid.UUID) -> dict[str, object]:
    """Once an agent or a bundle bought from an intention's decision is paid:
    the agents its buyer chose there, launched for them — « au retour du
    paiement, l'intention est relancée automatiquement » (2026-10-14)."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            row = await session.get(AddOnCheckout, checkout_id)
            if row is None or row.intention_id is None or row.requested_by is None:
                return {"status": "gone"}
            chosen = [
                Chosen(
                    str(each.get("key")),
                    dict(each.get("inputs") or {}),
                    [str(f) for f in each.get("formats") or []],
                    [uuid.UUID(str(x)) for x in each.get("sources") or []],
                )
                for each in row.launch
                if isinstance(each, dict) and each.get("key")
            ]
            try:
                launched = await launch(
                    session, workspace_id, row.intention_id, chosen, by=row.requested_by
                )
            except (AgentsRefusedError, IllegalTransitionError, NotYoursError) as error:
                logger.info(
                    "intention_bought_launch_refused",
                    intention=str(row.intention_id),
                    why=type(error).__name__,
                )
                return {"status": "refused"}
            if launched is None:
                return {"status": "gone"}
            _, runs = launched
            await session.commit()
    await queue_all(workspace_id, runs)
    return {"status": "launched", "runs": len(runs)}


def run_bought_launch(workspace_id: str, checkout_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    import asyncio

    return asyncio.run(launch_bought(uuid.UUID(workspace_id), uuid.UUID(checkout_id)))
