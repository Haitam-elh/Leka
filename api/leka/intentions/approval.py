"""Decisions on intentions (LEKA-390): opened when an analysis proposes to
act, voted on by people, the intention moved once decided — under the
workspace's governance (LEKA-404).

    the analysis (LEKA-388) moves an intention to awaiting_decision
      ──▶ open()     a decision: the actions proposed, their risk and why,
                     what it needs under the workspace's policy — approvals,
                     a role, how long an approval holds, when it is escalated;
                     linked to the intention; any earlier one still open
                     superseded. A freeze covering it: kept, it cannot be
                     approved while the freeze holds. A waiver covering it:
                     approved in advance by who granted the waiver.
      ──▶ vote()     approve, reject, modify, ask for changes — each kept with
                     who, for whom (a delegation), as which role, when, why
                     and the context it was cast in
      ──▶ decided    approved: the intention approved (LEKA-391 acts on it,
                     while the approval holds); rejected: the intention
                     rejected — nothing runs; changes asked: it waits for its
                     asker to ask again

The rules — what a vote may do, when a decision is decided, what the policy
says — are decisions.py's and governance.py's, pure. Here: reading and
keeping them.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.intentions.decisions import (
    APPROVING,
    DEFAULT_POLICY,
    REVERSIBLE,
    ApprovalPolicy,
    Change,
    DecisionStatus,
    PolicyError,
    Proposal,
    Requirement,
    Target,
    Verdict,
    Vote,
    classify,
    may_vote,
    modified,
    proposals_of,
    tally,
)
from leka.intentions.governance import (
    GovernanceException,
    PolicyDecision,
    authority_of,
    evaluate,
    freezes_of,
)
from leka.intentions.lifecycle import Actor, IntentionStatus
from leka.intentions.models import Intention, IntentionDecision, IntentionDecisionVote
from leka.intentions.oversight import OversightService
from leka.intentions.repository import IntentionRepository
from leka.intentions.schemas import (
    ApprovalPolicyRead,
    DecisionGovernanceRead,
    DecisionIntention,
    DecisionQueueItem,
    DecisionRead,
    DecisionSummary,
    DecisionVoteRead,
    PolicyVerdictRead,
    ProposalRead,
)
from leka.intentions.service import IntentionService
from leka.knowledge import Entity
from leka.platform import Workspace

S = IntentionStatus
POLICY_KEY = "approval_policy"
# Who may approve: whose authority a vote, or a waiver, rests on.
APPROVERS = ("admin", "owner")
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
    return [
        Vote(Verdict(r.verdict), r.by, r.revision, r.on_behalf_of, r.role)
        for r in rows
        if r.by is not None
    ]


def _hours(said: object) -> int | None:
    return said if isinstance(said, int) and not isinstance(said, bool) else None


def _requirement(decision: IntentionDecision) -> Requirement:
    said = (decision.governance or {}).get("requirement")
    kept = said if isinstance(said, Mapping) else {}
    return Requirement(
        decision.required_approvals,
        decision.separate_asker,
        role=decision.required_role,
        valid_hours=_hours(kept.get("valid_hours")),
        escalate_hours=_hours(kept.get("escalate_hours")),
    )


def _uuid(said: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(said)) if said else None
    except ValueError:
        return None


def waiver_of(decision: IntentionDecision) -> tuple[uuid.UUID, uuid.UUID] | None:
    """The waiver that approved it in advance, and who granted it — None
    when people decided it."""
    said = decision.governance or {}
    waiver, by = _uuid(said.get("waived_by")), _uuid(said.get("approved_by"))
    if decision.status != DecisionStatus.APPROVED or waiver is None or by is None:
        return None
    return waiver, by


def _approvers(
    decision: IntentionDecision, votes: Sequence[IntentionDecisionVote]
) -> tuple[uuid.UUID, ...]:
    waived = waiver_of(decision)
    if waived is not None:
        return (waived[1],)
    _, approvers = tally(
        _requirement(decision),
        asker=decision.asked_by,
        votes=_votes(votes),
        revision=decision.revision,
    )
    return approvers


def _governance_read(decision: IntentionDecision) -> DecisionGovernanceRead:
    said = decision.governance or {}
    need = _requirement(decision)
    reasons = said.get("reasons")
    exceptions = said.get("exceptions")
    escalate_at = said.get("escalate_at")
    return DecisionGovernanceRead.model_validate(
        {
            "reasons": reasons if isinstance(reasons, list) else [],
            "required_role": decision.required_role,
            "valid_hours": need.valid_hours,
            "escalate_at": escalate_at if isinstance(escalate_at, str) else None,
            "escalated_at": decision.escalated_at,
            "valid_until": decision.valid_until,
            "frozen": bool(said.get("frozen_by")),
            "waived": waiver_of(decision) is not None,
            "exceptions": exceptions if isinstance(exceptions, list) else [],
        }
    )


def decision_read(
    decision: IntentionDecision,
    intention: Intention,
    votes: Sequence[IntentionDecisionVote],
) -> DecisionRead:
    approvers = _approvers(decision, votes)
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
            "governance": _governance_read(decision),
        }
    )


async def approvers_of(session: AsyncSession, decision: IntentionDecision) -> tuple[uuid.UUID, ...]:
    """Whose authority approved its current revision, in order — who voted,
    or who delegated their vote, or who granted the waiver that approved it
    (LEKA-391 checks they still may)."""
    rows = (
        await session.scalars(
            select(IntentionDecisionVote)
            .where(IntentionDecisionVote.decision_id == decision.id)
            .order_by(IntentionDecisionVote.at, IntentionDecisionVote.created_at)
        )
    ).all()
    return _approvers(decision, rows)


def verdict_read(decision: PolicyDecision) -> PolicyVerdictRead:
    need = decision.requirement
    return PolicyVerdictRead.model_validate(
        {
            "risk": decision.risk,
            "reasons": [r.as_dict() for r in decision.reasons],
            "approvals": need.approvals,
            "separate": need.separate,
            "role": need.role,
            "valid_hours": need.valid_hours,
            "escalate_hours": need.escalate_hours,
            "frozen": decision.frozen,
            "waived": decision.waived_by is not None,
            "exceptions": [dict(e) for e in decision.exceptions],
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

    async def set_policy(
        self, change: Mapping[str, object], *, by: uuid.UUID | None = None
    ) -> ApprovalPolicyRead:
        """The policy changed: what is said replaces what was — per risk,
        what a risk is not said of kept; PolicyError when it cannot be. Kept
        in the governance trail, before and after. Decisions already open
        keep theirs; an approved one not yet run is checked against it."""
        workspace = await self._workspace()
        current = ApprovalPolicy.from_settings(workspace.settings.get(POLICY_KEY)).to_settings()
        merged: dict[str, object] = dict(current)
        for key in ("approvals", "roles", "valid_hours", "escalate_hours"):
            said = change.get(key)
            if said is not None:
                merged[key] = {**dict(current[key]), **dict(said)}  # type: ignore[call-overload]
        for key in ("separate", "production_raises", "rules"):
            if change.get(key) is not None:
                merged[key] = change[key]
        approvals = cast("dict[str, int]", merged["approvals"])
        if "critical" not in dict(change.get("approvals") or {}):  # type: ignore[call-overload]
            # Said before critical was a risk: it asks at least what high does.
            approvals["critical"] = max(approvals["critical"], approvals["high"])
        policy = ApprovalPolicy.from_settings(merged)
        after = policy.to_settings()
        workspace.settings = {**workspace.settings, POLICY_KEY: after}
        if after != current:
            OversightService(self._session, self._workspace_id).record(
                "policy_changed",
                by=by,
                detail={
                    "changed": sorted(k for k in after if after[k] != current[k]),
                    "before": current,
                    "after": after,
                },
            )
        await self._session.flush()
        return policy_read(after)

    # ── what the policy says ────────────────────────────────────────────────

    async def _criticality(self, proposals: Sequence[Proposal]) -> dict[uuid.UUID, str | None]:
        """How critical what they act on is, as the company model says."""
        ids = {t.id for p in proposals for t in p.targets}
        if not ids:
            return {}
        rows = await self._session.execute(
            select(Entity.id, Entity.attributes["criticality"].astext).where(
                Entity.workspace_id == self._workspace_id, Entity.id.in_(ids)
            )
        )
        return {i: (level or None) for i, level in rows.tuples()}

    async def _exceptions(
        self, oversight: OversightService, now: datetime
    ) -> list[GovernanceException]:
        """The exceptions that may hold now — a waiver only while who granted
        it may still approve: their approval is what it gives."""
        found = await oversight.exceptions(now)
        grantors = {e.granted_by for e in found if e.kind == "waiver" and e.granted_by}
        able = {g for g in grantors if await oversight.role_of(g) in APPROVERS}
        return [e for e in found if e.kind != "waiver" or e.granted_by in able]

    async def evaluate(
        self,
        proposals: Sequence[Proposal],
        *,
        analysis_risk: str | None,
        policy: ApprovalPolicy | None = None,
        now: datetime | None = None,
    ) -> PolicyDecision:
        """What the workspace's policy says of these actions, now."""
        moment = _now(now)
        oversight = OversightService(self._session, self._workspace_id)
        return evaluate(
            proposals,
            analysis_risk=analysis_risk,
            policy=policy or (await self.policy())[0],
            exceptions=await self._exceptions(oversight, moment),
            criticality=await self._criticality(proposals),
            now=moment,
        )

    async def probe(
        self,
        action: str,
        *,
        environment: str | None,
        targets: Sequence[uuid.UUID],
        analysis_risk: str | None,
        now: datetime | None = None,
    ) -> PolicyVerdictRead:
        """What the policy would say of an action, were it proposed now — on
        things of the company model; one it does not hold is left out."""
        rows = (
            await self._session.execute(
                select(Entity.id, Entity.name, Entity.type).where(
                    Entity.workspace_id == self._workspace_id,
                    Entity.id.in_(set(targets) or {uuid.uuid4()}),
                )
            )
        ).tuples()
        proposal = Proposal(
            id=action,
            action=action,
            targets=tuple(Target(i, n, t) for i, n, t in rows),
            environment=environment,
            reversible=REVERSIBLE.get(action),
        )
        return verdict_read(await self.evaluate([proposal], analysis_risk=analysis_risk, now=now))

    # ── opening ─────────────────────────────────────────────────────────────

    async def open(
        self,
        intention: Intention,
        *,
        actions: Sequence[tuple[str, bool]],
        targets: Sequence[Target],
        environment: str | None,
        constraints: Sequence[tuple[str, object, bool]],
        action_targets: Mapping[str, Sequence[uuid.UUID]] | None = None,
        analysis_id: uuid.UUID | None,
        context_version: int | None,
        analysis_risk: str | None,
        now: datetime | None = None,
    ) -> Opened | None:
        """A decision on what the intention asks to do — none when it asks
        to change nothing. Any earlier one still waiting is superseded."""
        proposals = proposals_of(actions, targets, environment, constraints, action_targets)
        if not proposals:
            return None
        moment = _now(now)
        policy, _ = await self.policy()
        said = await self.evaluate(
            proposals, analysis_risk=analysis_risk, policy=policy, now=moment
        )
        need = said.requirement
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
            risk=said.risk,
            revision=1,
            required_approvals=need.approvals,
            separate_asker=need.separate,
            required_role=need.role,
            policy=policy.to_settings(),
            governance=said.as_dict(),
            proposals=[p.as_dict() for p in proposals],
            detail={},
            created_at=moment,
        )
        self._session.add(decision)
        await self._session.flush()
        oversight = OversightService(self._session, self._workspace_id)
        if said.frozen:
            oversight.record(
                "decision_frozen",
                by=None,
                subject_id=decision.id,
                detail={
                    "intention_id": str(intention.id),
                    "risk": said.risk,
                    "exceptions": [str(i) for i in said.frozen_by],
                },
                now=moment,
            )
        elif said.waived_by is not None and said.approved_by is not None:
            await self._waived(intention, decision, said, oversight, moment)
        await self._session.flush()
        return Opened(decision, len(earlier))

    async def _waived(
        self,
        intention: Intention,
        decision: IntentionDecision,
        said: PolicyDecision,
        oversight: OversightService,
        moment: datetime,
    ) -> None:
        """Approved in advance by who granted the waiver: a standard change
        — the intention moved in their name, the waiver said."""
        waiver = next((e for e in said.exceptions if e.get("kind") == "waiver"), {})
        decision.status = DecisionStatus.APPROVED
        decision.decided_at = moment
        if said.requirement.valid_hours:
            decision.valid_until = moment + timedelta(hours=said.requirement.valid_hours)
        oversight.record(
            "decision_waived",
            by=said.approved_by,
            subject_id=decision.id,
            detail={
                "intention_id": str(intention.id),
                "risk": said.risk,
                "exception": str(said.waived_by),
                "reason": waiver.get("reason"),
            },
            now=moment,
        )
        await IntentionService(self._intentions).move(
            intention.id,
            S.APPROVED,
            actor=Actor.PERSON,
            by=said.approved_by,
            reason=str(waiver.get("reason") or "") or None,
            detail={
                "decision_id": str(decision.id),
                "number": decision.number,
                "risk": decision.risk,
                "revision": decision.revision,
                "approvers": [str(said.approved_by)],
                "waived_by": str(said.waived_by),
            },
            now=moment,
        )

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

    async def risk_open(self, intention_id: uuid.UUID) -> str | None:
        """The risk of its latest decision — what an authorization reads of
        a vote on it (LEKA-403's policies by risk); None when it has none."""
        risk: str | None = await self._session.scalar(
            select(IntentionDecision.risk)
            .where(IntentionDecision.intention_id == intention_id)
            .order_by(IntentionDecision.number.desc())
            .limit(1)
        )
        return risk

    async def vote(
        self,
        intention_id: uuid.UUID,
        verdict: Verdict,
        *,
        by: uuid.UUID,
        reason: str | None = None,
        change: Change | None = None,
        on_behalf_of: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> DecisionRead | None:
        """A person's vote on the decision open on this intention — kept
        with its context; the intention moved once it is decided. Cast for
        someone else (`on_behalf_of`) only under a delegation of theirs that
        holds now, at this risk. None when the intention is not there;
        DecisionClosedError when nothing is open; DecisionRefusedError when
        this vote may not be cast."""
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
        moment = _now(now)
        oversight = OversightService(self._session, self._workspace_id)
        delegation = None
        if on_behalf_of is not None:
            # Never one's own: no one delegates to themselves.
            delegation = authority_of(
                by, on_behalf_of, await oversight.delegations(moment), decision.risk, moment
            )
            if delegation is None or await oversight.role_of(on_behalf_of) not in APPROVERS:
                raise DecisionRefusedError("no_delegation", _REFUSALS["no_delegation"])
        if verdict in APPROVING:
            proposals = [Proposal.from_dict(p) for p in decision.proposals]
            frozen = freezes_of(proposals, await oversight.exceptions(moment), moment)
            if frozen:
                raise DecisionRefusedError(
                    "frozen", f"{_REFUSALS['frozen']} {frozen[0].reason}".strip()
                )
        rows = (await self._votes_of([decision.id]))[decision.id]
        votes = _votes(rows)
        refusal = may_vote(
            verdict,
            by=by,
            asker=decision.asked_by,
            requirement=_requirement(decision),
            votes=votes,
            revision=decision.revision,
            on_behalf_of=on_behalf_of,
        )
        if refusal is not None:
            raise DecisionRefusedError(refusal.code, _REFUSALS[refusal.code])
        role = await oversight.role_of(on_behalf_of or by)
        changes: dict[str, object] = {}
        if verdict is Verdict.MODIFY:
            changes = await self._modify(decision, change or Change())
        context = {
            "risk": decision.risk,
            "revision": decision.revision,
            "required_approvals": decision.required_approvals,
            "separate_asker": decision.separate_asker,
            "required_role": decision.required_role,
            "proposals": decision.proposals,
            "analysis_id": str(decision.analysis_id) if decision.analysis_id else None,
            "context_version": decision.context_version,
            "intention_status": intention.status,
            "role": role,
            "delegation_id": str(delegation.id) if delegation else None,
        }
        cast = IntentionDecisionVote(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            decision_id=decision.id,
            revision=decision.revision,
            verdict=verdict,
            by=by,
            on_behalf_of=on_behalf_of,
            role=role,
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
            valid = _requirement(decision).valid_hours
            if status is DecisionStatus.APPROVED and valid:
                decision.valid_until = moment + timedelta(hours=valid)
            await self._decided(intention, decision, status, approvers, by, reason, moment)
        await self._session.flush()
        return decision_read(decision, intention, rows)

    async def _modify(self, decision: IntentionDecision, change: Change) -> dict[str, object]:
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
        risk, reasons = classify(
            decision.analysis_risk, after, policy, await self._criticality(after)
        )
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
        decision.required_role = need.role
        decision.governance = {
            **(decision.governance or {}),
            "risk": risk,
            "reasons": [r.as_dict() for r in reasons],
            "requirement": {
                "approvals": need.approvals,
                "separate": need.separate,
                "role": need.role,
                "valid_hours": need.valid_hours,
                "escalate_hours": need.escalate_hours,
            },
        }
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
    "no_delegation": (
        "No delegation lets you vote for them now, on a decision this risky — or they may no "
        "longer approve."
    ),
    "frozen": "A freeze covers it: it cannot be approved while the freeze holds.",
}
