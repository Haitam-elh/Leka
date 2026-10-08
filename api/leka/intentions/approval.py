"""Decisions on intentions (LEKA-390): opened when an analysis proposes to
act, voted on by people, the intention moved once decided.

    the analysis (LEKA-388) moves an intention to awaiting_decision
      ──▶ open()     a decision: the actions proposed, the risk, how many must
                     approve under the workspace's policy; linked to the
                     intention; any earlier one still open superseded
      ──▶ vote()     approve, reject, modify, ask for changes — each kept with
                     who, when, why and the context it was cast in
      ──▶ decided    approved: the intention approved (LEKA-391 acts on it);
                     rejected: the intention rejected — nothing runs;
                     changes asked: it waits for its asker to ask again

The rules — what a vote may do, when a decision is decided — are
decisions.py's, pure. Here: reading and keeping them.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.intentions.decisions import (
    DEFAULT_POLICY,
    ApprovalPolicy,
    Change,
    DecisionStatus,
    PolicyError,
    Proposal,
    Requirement,
    Target,
    Verdict,
    Vote,
    environment_of,
    may_vote,
    modified,
    proposals_of,
    risk_of,
    tally,
)
from leka.intentions.lifecycle import Actor, IntentionStatus
from leka.intentions.models import Intention, IntentionDecision, IntentionDecisionVote
from leka.intentions.repository import IntentionRepository
from leka.intentions.schemas import (
    ApprovalPolicyRead,
    DecisionIntention,
    DecisionQueueItem,
    DecisionRead,
    DecisionSummary,
    DecisionVoteRead,
    ProposalRead,
)
from leka.intentions.service import IntentionService
from leka.platform import Workspace

S = IntentionStatus
POLICY_KEY = "approval_policy"
# Kept for the queue, at most: what waits, the most recent decided.
QUEUE = 200


class DecisionRefusedError(Exception):
    """A vote that cannot be cast: its code says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DecisionClosedError(Exception):
    """Nothing to vote on: no decision open on this intention."""


@dataclass(frozen=True)
class Opened:
    decision: IntentionDecision
    superseded: int


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _votes(rows: Sequence[IntentionDecisionVote]) -> list[Vote]:
    return [Vote(Verdict(r.verdict), r.by, r.revision) for r in rows if r.by is not None]


def _requirement(decision: IntentionDecision) -> Requirement:
    return Requirement(decision.required_approvals, decision.separate_asker)


def decision_read(
    decision: IntentionDecision,
    intention: Intention,
    votes: Sequence[IntentionDecisionVote],
) -> DecisionRead:
    _, approvers = tally(
        _requirement(decision),
        asker=decision.asked_by,
        votes=_votes(votes),
        revision=decision.revision,
    )
    proposed = decision.status == DecisionStatus.PROPOSED
    waiting = (
        proposed and intention.status == S.AWAITING_DECISION.value and intention.archived_at is None
    )
    # Its intention cancelled, asked again, archived: no longer the one.
    behind = proposed and not waiting
    return DecisionRead.model_validate(
        {
            "id": decision.id,
            "intention_id": decision.intention_id,
            "number": decision.number,
            "status": DecisionStatus.SUPERSEDED if behind else decision.status,
            "open": waiting,
            "risk": decision.risk,
            "analysis_risk": decision.analysis_risk,
            "revision": decision.revision,
            "required_approvals": decision.required_approvals,
            "separate_asker": decision.separate_asker,
            "approvers": list(approvers),
            "proposals": [ProposalRead.model_validate(p) for p in decision.proposals],
            "analysis_id": decision.analysis_id,
            "context_version": decision.context_version,
            "asked_by": decision.asked_by,
            "created_at": decision.created_at,
            "decided_at": decision.decided_at,
            "votes": [
                DecisionVoteRead.model_validate(vote, from_attributes=True) for vote in votes
            ],
        }
    )


def policy_read(said: object) -> ApprovalPolicyRead:
    policy = ApprovalPolicy.from_settings(said)
    kept = policy.to_settings()
    return ApprovalPolicyRead.model_validate({**kept, "customised": said is not None})


class DecisionService:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._intentions = IntentionRepository(session, workspace_id)

    # ── the policy ──────────────────────────────────────────────────────────

    async def _workspace(self) -> Workspace:
        workspace = await self._session.get(Workspace, self._workspace_id)
        if workspace is None:
            msg = "the workspace is gone"
            raise LookupError(msg)
        return workspace

    async def policy(self) -> tuple[ApprovalPolicy, object]:
        """The workspace's policy — LEKA's default for what it does not say
        — and what its settings keep."""
        said = (await self._workspace()).settings.get(POLICY_KEY)
        try:
            return ApprovalPolicy.from_settings(said), said
        except PolicyError:
            # Kept before a rule tightened: the default, rather than none.
            return DEFAULT_POLICY, None

    async def set_policy(self, change: Mapping[str, object]) -> ApprovalPolicyRead:
        """The policy changed: what is said replaces what was; PolicyError
        when it cannot be. Decisions already open keep theirs."""
        workspace = await self._workspace()
        current = ApprovalPolicy.from_settings(workspace.settings.get(POLICY_KEY)).to_settings()
        merged: dict[str, object] = {
            "approvals": {**dict(current["approvals"]), **dict(change.get("approvals") or {})},  # type: ignore[call-overload]
            "separate": current["separate"]
            if change.get("separate") is None
            else change["separate"],
            "production_raises": current["production_raises"]
            if change.get("production_raises") is None
            else change["production_raises"],
        }
        policy = ApprovalPolicy.from_settings(merged)
        workspace.settings = {**workspace.settings, POLICY_KEY: policy.to_settings()}
        return policy_read(policy.to_settings())

    # ── opening ─────────────────────────────────────────────────────────────

    async def open(
        self,
        intention: Intention,
        *,
        actions: Sequence[tuple[str, bool]],
        targets: Sequence[Target],
        environment: str | None,
        constraints: Sequence[tuple[str, object, bool]],
        analysis_id: uuid.UUID | None,
        context_version: int | None,
        analysis_risk: str | None,
        now: datetime | None = None,
    ) -> Opened | None:
        """A decision on what the intention asks to do — none when it asks
        to change nothing. Any earlier one still waiting is superseded."""
        proposals = proposals_of(actions, targets, environment, constraints)
        if not proposals:
            return None
        policy, _ = await self.policy()
        risk = risk_of(analysis_risk, environment_of(proposals), policy)
        need = policy.requirement(risk)
        earlier = (
            await self._session.scalars(
                select(IntentionDecision).where(
                    IntentionDecision.intention_id == intention.id,
                    IntentionDecision.status.in_(
                        (DecisionStatus.PROPOSED, DecisionStatus.CHANGES_REQUESTED)
                    ),
                )
            )
        ).all()
        moment = _now(now)
        for old in earlier:
            old.status = DecisionStatus.SUPERSEDED
            old.decided_at = old.decided_at or moment
        number = (
            await self._session.scalar(
                select(func.max(IntentionDecision.number)).where(
                    IntentionDecision.intention_id == intention.id
                )
            )
            or 0
        ) + 1
        decision = IntentionDecision(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            intention_id=intention.id,
            number=number,
            status=DecisionStatus.PROPOSED,
            analysis_id=analysis_id,
            context_version=context_version,
            asked_by=intention.created_by,
            analysis_risk=analysis_risk,
            risk=risk,
            revision=1,
            required_approvals=need.approvals,
            separate_asker=need.separate,
            policy=policy.to_settings(),
            proposals=[p.as_dict() for p in proposals],
            detail={},
            created_at=moment,
        )
        self._session.add(decision)
        await self._session.flush()
        return Opened(decision, len(earlier))

    # ── reading ─────────────────────────────────────────────────────────────

    async def _votes_of(
        self, ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[IntentionDecisionVote]]:
        found: dict[uuid.UUID, list[IntentionDecisionVote]] = {i: [] for i in ids}
        if not ids:
            return found
        rows = await self._session.scalars(
            select(IntentionDecisionVote)
            .where(IntentionDecisionVote.decision_id.in_(ids))
            .order_by(IntentionDecisionVote.at, IntentionDecisionVote.created_at)
        )
        for row in rows:
            found[row.decision_id].append(row)
        return found

    async def decisions(self, intention_id: uuid.UUID) -> list[DecisionRead] | None:
        """Every decision on it, the latest first — None when it is not
        there."""
        intention = await self._intentions.intention(intention_id)
        if intention is None:
            return None
        rows = (
            await self._session.scalars(
                select(IntentionDecision)
                .where(IntentionDecision.intention_id == intention_id)
                .order_by(IntentionDecision.number.desc())
            )
        ).all()
        votes = await self._votes_of([r.id for r in rows])
        return [decision_read(r, intention, votes[r.id]) for r in rows]

    def _waiting(self) -> ColumnElement[bool]:
        """Proposed, and its intention still awaiting a decision: an
        intention cancelled or asked again leaves its decision behind."""
        return (IntentionDecision.status == DecisionStatus.PROPOSED) & (
            (Intention.status == S.AWAITING_DECISION.value) & Intention.archived_at.is_(None)
        )

    async def queue(
        self, statuses: Sequence[str], *, limit: int = QUEUE
    ) -> list[DecisionQueueItem]:
        """The decisions in these states, the latest first, each with its
        intention — what À valider lists. A proposed one left behind by its
        intention is listed as superseded."""
        waiting = self._waiting()
        others = [s for s in statuses if s != DecisionStatus.PROPOSED]
        wanted: ColumnElement[bool] = IntentionDecision.status.in_(others)
        if DecisionStatus.PROPOSED in statuses:
            wanted = wanted | waiting
        if DecisionStatus.SUPERSEDED in statuses:
            wanted = wanted | ((IntentionDecision.status == DecisionStatus.PROPOSED) & ~waiting)
        rows = (
            (
                await self._session.execute(
                    select(IntentionDecision, Intention)
                    .join(
                        Intention,
                        (Intention.id == IntentionDecision.intention_id)
                        & (Intention.workspace_id == IntentionDecision.workspace_id),
                    )
                    .where(IntentionDecision.workspace_id == self._workspace_id, wanted)
                    .order_by(IntentionDecision.created_at.desc())
                    .limit(limit)
                )
            )
            .tuples()
            .all()
        )
        votes = await self._votes_of([d.id for d, _ in rows])
        return [
            DecisionQueueItem(
                decision=decision_read(d, i, votes[d.id]),
                intention=DecisionIntention(
                    id=i.id,
                    title=i.title,
                    status=i.status,
                    kind=i.kind,
                    created_by=i.created_by,
                    summary=i.summary,
                ),
            )
            for d, i in rows
        ]

    async def summary(self) -> DecisionSummary:
        """How many stand where — a proposed one left behind by its
        intention counted as superseded."""
        state = case(
            (
                (IntentionDecision.status == DecisionStatus.PROPOSED) & ~self._waiting(),
                DecisionStatus.SUPERSEDED.value,
            ),
            else_=IntentionDecision.status,
        )
        rows = await self._session.execute(
            select(state, func.count())
            .join(
                Intention,
                (Intention.id == IntentionDecision.intention_id)
                & (Intention.workspace_id == IntentionDecision.workspace_id),
            )
            .where(IntentionDecision.workspace_id == self._workspace_id)
            .group_by(state)
        )
        counts = dict.fromkeys(DecisionStatus, 0)
        for status, count in rows.tuples():
            counts[DecisionStatus(status)] = count
        return DecisionSummary.model_validate({k.value: v for k, v in counts.items()})

    # ── voting ──────────────────────────────────────────────────────────────

    async def vote(
        self,
        intention_id: uuid.UUID,
        verdict: Verdict,
        *,
        by: uuid.UUID,
        reason: str | None = None,
        change: Change | None = None,
        now: datetime | None = None,
    ) -> DecisionRead | None:
        """A person's vote on the decision open on this intention — kept
        with its context; the intention moved once it is decided. None
        when the intention is not there; DecisionClosedError when nothing
        is open; DecisionRefusedError when this vote may not be cast."""
        intention = await self._intentions.intention(intention_id, lock=True)
        if intention is None:
            return None
        decision = await self._session.scalar(
            select(IntentionDecision)
            .where(IntentionDecision.intention_id == intention_id)
            .order_by(IntentionDecision.number.desc())
            .limit(1)
            .with_for_update()
        )
        if (
            decision is None
            or decision.status != DecisionStatus.PROPOSED
            or intention.status != S.AWAITING_DECISION.value
            or intention.archived_at is not None
        ):
            raise DecisionClosedError
        reason = (reason or "").strip() or None
        if verdict is not Verdict.APPROVE and reason is None:
            raise DecisionRefusedError("reason_required", "Say why: it is kept with the decision.")
        rows = (await self._votes_of([decision.id]))[decision.id]
        votes = _votes(rows)
        refusal = may_vote(
            verdict,
            by=by,
            asker=decision.asked_by,
            requirement=_requirement(decision),
            votes=votes,
            revision=decision.revision,
        )
        if refusal is not None:
            raise DecisionRefusedError(refusal.code, _REFUSALS[refusal.code])
        moment = _now(now)
        changes: dict[str, object] = {}
        if verdict is Verdict.MODIFY:
            changes = self._modify(decision, change or Change())
        context = {
            "risk": decision.risk,
            "revision": decision.revision,
            "required_approvals": decision.required_approvals,
            "separate_asker": decision.separate_asker,
            "proposals": decision.proposals,
            "analysis_id": str(decision.analysis_id) if decision.analysis_id else None,
            "context_version": decision.context_version,
            "intention_status": intention.status,
        }
        cast = IntentionDecisionVote(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            decision_id=decision.id,
            revision=decision.revision,
            verdict=verdict,
            by=by,
            at=moment,
            reason=reason,
            changes=changes,
            context=context,
        )
        self._session.add(cast)
        rows = [*rows, cast]
        status, approvers = tally(
            _requirement(decision),
            asker=decision.asked_by,
            votes=_votes(rows),
            revision=decision.revision,
        )
        if status is not DecisionStatus.PROPOSED:
            decision.status = status
            decision.decided_at = moment
            await self._decided(intention, decision, status, approvers, by, reason, moment)
        await self._session.flush()
        return decision_read(decision, intention, rows)

    def _modify(self, decision: IntentionDecision, change: Change) -> dict[str, object]:
        """The next revision: the proposals as changed, its risk and what it
        needs read again under the policy it was opened with."""
        before = [Proposal.from_dict(p) for p in decision.proposals]
        try:
            after = modified(before, change)
        except ValueError as error:
            raise DecisionRefusedError("invalid_change", str(error)) from error
        if after == tuple(before):
            raise DecisionRefusedError("nothing_changed", "Nothing would change: approve it.")
        policy = ApprovalPolicy.from_settings(decision.policy or None)
        risk = risk_of(decision.analysis_risk, environment_of(after), policy)
        need = policy.requirement(risk)
        said: dict[str, object] = {
            "from": {
                "proposals": decision.proposals,
                "risk": decision.risk,
                "revision": decision.revision,
            },
            "to": {
                "proposals": [p.as_dict() for p in after],
                "risk": risk,
                "revision": decision.revision + 1,
            },
        }
        decision.revision += 1
        decision.proposals = [p.as_dict() for p in after]
        decision.risk = risk
        decision.required_approvals = need.approvals
        decision.separate_asker = need.separate
        return said

    async def _decided(
        self,
        intention: Intention,
        decision: IntentionDecision,
        status: DecisionStatus,
        approvers: Sequence[uuid.UUID],
        by: uuid.UUID,
        reason: str | None,
        moment: datetime,
    ) -> None:
        """The intention moved by the person whose vote decided it."""
        detail = {
            "decision_id": str(decision.id),
            "number": decision.number,
            "risk": decision.risk,
            "revision": decision.revision,
            "approvers": [str(a) for a in approvers],
        }
        moves = {DecisionStatus.APPROVED: S.APPROVED, DecisionStatus.REJECTED: S.REJECTED}
        if status in moves:
            await IntentionService(self._intentions).move(
                intention.id,
                moves[status],
                actor=Actor.PERSON,
                by=by,
                reason=reason,
                detail=detail,
                now=moment,
            )


_REFUSALS = {
    "asker_may_not_approve": (
        "The policy wants someone else than who asked to approve an action this risky."
    ),
    "already_approved": "Already approved by you: another person's approval is needed.",
}
