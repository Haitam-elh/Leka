"""Governance of consequential actions (LEKA-404), pure: what the
workspace's policy says of actions proposed — their risk and why, who must
approve, whether something freezes them or waives approval — and what the
execution layer checks before it acts.

    evaluate()   the actions proposed, under the policy, its exceptions, now:
                   the risk, and every reason it is that risk (decisions.py)
                   what it needs: approvals, the asker apart, a role, how long
                     an approval holds, when it is escalated
                   frozen      an active freeze covers one of them: it cannot
                               be approved, nor run, until the freeze ends
                   waived      an active waiver covers them all, at or below
                               its risk: a standard change, approved by the
                               policy — no one need vote
    EXCEPTIONS   an admin's, said why, from when to when, on what: actions,
                 environments, things — none said: any. A freeze stops what
                 it covers; a waiver pre-approves it. Revoked, it no longer
                 holds; kept either way.
    DELEGATION   an approver lends their authority to another member, from
                 when to when, up to a risk: the other votes on their behalf,
                 the vote counted as theirs, kept as both. Never to oneself.
    policy_checks()   before an action runs (actions.py, execution.py): no
                 freeze covers it now; its approval still holds; what
                 approved it still meets what the policy asks now — or the
                 waiver that approved it is not revoked.
    escalation_due()  a decision waiting past its requirement's hours.

Nothing here reads a database: approval.py and actions.py read, keep and
call this.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from leka.intentions.decisions import (
    RANK,
    RISKS,
    ApprovalPolicy,
    Proposal,
    Reason,
    Requirement,
    classify,
    in_production,
    role_holds,
)

EXCEPTION_KINDS = ("freeze", "waiver")
# A waiver covers at most this: never what is high or critical.
MOST_WAIVED = "medium"
# How long an exception or a delegation may last, at most.
LONGEST = timedelta(days=90)


class GovernanceError(ValueError):
    """An exception or a delegation that cannot be granted as said."""


@dataclass(frozen=True)
class Scope:
    """What an exception covers: an action of these kinds, in these
    environments, on one of these things — a list left empty, any."""

    actions: frozenset[str] = frozenset()
    environments: frozenset[str] = frozenset()
    targets: frozenset[uuid.UUID] = frozenset()

    def covers(self, proposal: Proposal) -> bool:
        if self.actions and proposal.action not in self.actions:
            return False
        if self.environments:
            where = (proposal.environment or "").casefold()
            names = {e.casefold() for e in self.environments}
            if not (where in names or ("production" in names and in_production(where))):
                return False
        return not self.targets or any(t.id in self.targets for t in proposal.targets)


@dataclass(frozen=True)
class GovernanceException:
    """A freeze — what it covers cannot be approved nor run — or a waiver —
    what it covers, up to its risk, is approved by the policy."""

    id: uuid.UUID
    kind: str
    scope: Scope
    starts_at: datetime
    ends_at: datetime
    reason: str
    granted_by: uuid.UUID | None
    # A waiver's: the riskiest it covers.
    max_risk: str = "low"
    revoked_at: datetime | None = None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.starts_at <= now < self.ends_at


@dataclass(frozen=True)
class Delegation:
    """An approver's authority, lent: from when to when, up to a risk."""

    id: uuid.UUID
    by: uuid.UUID
    to: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    max_risk: str
    reason: str
    revoked_at: datetime | None = None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.starts_at <= now < self.ends_at

    def allows(self, risk: str, now: datetime) -> bool:
        return self.active(now) and RANK[risk] <= RANK[self.max_risk]


def checked_window(starts_at: datetime, ends_at: datetime) -> None:
    if ends_at <= starts_at:
        raise GovernanceError("It must end after it starts.")
    if ends_at - starts_at > LONGEST:
        raise GovernanceError(f"{LONGEST.days} days at most.")


def checked_exception(exception: GovernanceException) -> GovernanceException:
    """It, if it can be granted as said — else GovernanceError."""
    if exception.kind not in EXCEPTION_KINDS:
        raise GovernanceError("An exception is a freeze or a waiver.")
    if not exception.reason.strip():
        raise GovernanceError("Say why: it is kept with the exception.")
    checked_window(exception.starts_at, exception.ends_at)
    if exception.kind == "waiver":
        if exception.max_risk not in RANK or RANK[exception.max_risk] > RANK[MOST_WAIVED]:
            raise GovernanceError(
                f"A waiver covers at most a {MOST_WAIVED} risk: what is riskier is decided."
            )
        if not (exception.scope.actions and exception.scope.environments):
            raise GovernanceError("A waiver names its actions and its environments.")
    return exception


def checked_delegation(delegation: Delegation) -> Delegation:
    if delegation.by == delegation.to:
        raise GovernanceError("One does not delegate to oneself.")
    if delegation.max_risk not in RANK:
        raise GovernanceError(f"Up to a risk: {', '.join(RISKS)}.")
    if not delegation.reason.strip():
        raise GovernanceError("Say why: it is kept with the delegation.")
    checked_window(delegation.starts_at, delegation.ends_at)
    return delegation


@dataclass(frozen=True)
class PolicyDecision:
    """What the policy says of actions proposed, now."""

    risk: str
    reasons: tuple[Reason, ...]
    requirement: Requirement
    frozen_by: tuple[uuid.UUID, ...] = ()
    waived_by: uuid.UUID | None = None
    # Who approved it in advance: the waiver's grantor.
    approved_by: uuid.UUID | None = None
    escalate_at: datetime | None = None
    exceptions: tuple[Mapping[str, object], ...] = field(default_factory=tuple)

    @property
    def frozen(self) -> bool:
        return bool(self.frozen_by)

    def as_dict(self) -> dict[str, object]:
        return {
            "risk": self.risk,
            "reasons": [r.as_dict() for r in self.reasons],
            "requirement": {
                "approvals": self.requirement.approvals,
                "separate": self.requirement.separate,
                "role": self.requirement.role,
                "valid_hours": self.requirement.valid_hours,
                "escalate_hours": self.requirement.escalate_hours,
            },
            "frozen_by": [str(i) for i in self.frozen_by],
            "waived_by": str(self.waived_by) if self.waived_by else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "escalate_at": self.escalate_at.isoformat() if self.escalate_at else None,
            "exceptions": [dict(e) for e in self.exceptions],
        }


def _said(exception: GovernanceException) -> dict[str, object]:
    return {
        "id": str(exception.id),
        "kind": exception.kind,
        "reason": exception.reason,
        "ends_at": exception.ends_at.isoformat(),
    }


def freezes_of(
    proposals: Sequence[Proposal], exceptions: Sequence[GovernanceException], now: datetime
) -> list[GovernanceException]:
    """The freezes that hold now over one of these actions."""
    return [
        e
        for e in exceptions
        if e.kind == "freeze" and e.active(now) and any(e.scope.covers(p) for p in proposals)
    ]


def evaluate(
    proposals: Sequence[Proposal],
    *,
    analysis_risk: str | None,
    policy: ApprovalPolicy,
    exceptions: Sequence[GovernanceException] = (),
    criticality: Mapping[uuid.UUID, str | None] | None = None,
    now: datetime,
) -> PolicyDecision:
    """The policy, applied to actions proposed now."""
    risk, reasons = classify(analysis_risk, proposals, policy, criticality)
    need = policy.requirement(risk)
    freezes = tuple(freezes_of(proposals, exceptions, now))
    waiver = next(
        (
            e
            for e in exceptions
            if e.kind == "waiver"
            and e.active(now)
            and e.granted_by is not None
            and RANK[risk] <= RANK[e.max_risk]
            and proposals
            and all(e.scope.covers(p) for p in proposals)
        ),
        None,
    )
    return PolicyDecision(
        risk=risk,
        reasons=reasons,
        requirement=need,
        frozen_by=tuple(e.id for e in freezes),
        # A freeze wins over a waiver: nothing frozen is approved.
        waived_by=waiver.id if waiver is not None and not freezes else None,
        approved_by=waiver.granted_by if waiver is not None and not freezes else None,
        escalate_at=now + timedelta(hours=need.escalate_hours) if need.escalate_hours else None,
        exceptions=tuple(_said(e) for e in (*freezes, *([waiver] if waiver else []))),
    )


def authority_of(
    by: uuid.UUID,
    on_behalf_of: uuid.UUID | None,
    delegations: Sequence[Delegation],
    risk: str,
    now: datetime,
) -> Delegation | None:
    """The delegation `by` votes under for `on_behalf_of` — None when there
    is none that allows it now, at this risk."""
    if on_behalf_of is None:
        return None
    return next(
        (d for d in delegations if d.by == on_behalf_of and d.to == by and d.allows(risk, now)),
        None,
    )


def escalation_due(
    created_at: datetime,
    requirement: Requirement,
    now: datetime,
    *,
    escalated_at: datetime | None,
) -> bool:
    """Whether a decision still waiting is due to be escalated — once."""
    if escalated_at is not None or not requirement.escalate_hours:
        return False
    return now >= created_at + timedelta(hours=requirement.escalate_hours)


@dataclass(frozen=True)
class PolicyCheck:
    """One thing the policy says must hold before an action runs."""

    code: str
    passed: bool
    detail: Mapping[str, object] = field(default_factory=dict)


def policy_checks(
    proposals: Sequence[Proposal],
    *,
    risk: str,
    valid_until: datetime | None,
    approvals: int,
    roles: Sequence[str | None],
    policy: ApprovalPolicy,
    exceptions: Sequence[GovernanceException],
    now: datetime,
    waived: bool | None = None,
) -> list[PolicyCheck]:
    """What the policy says of an approved decision, as things stand now:
    no freeze covers it; its approval still holds; what approved it meets
    what the policy asks of its risk today — a policy tightened since asks
    again — or, approved by a waiver (`waived` said), the waiver is not
    revoked. `approvals` and `roles`: its approvers who still may approve,
    and their roles now."""
    freezes = freezes_of(proposals, exceptions, now)
    found = [PolicyCheck("not_frozen", not freezes, {"by": [_said(e) for e in freezes]})]
    if valid_until is not None:
        found.append(
            PolicyCheck("approval_valid", now < valid_until, {"until": valid_until.isoformat()})
        )
    if waived is not None:
        found.append(PolicyCheck("waiver_holds", waived))
        return found
    need = policy.requirement(risk)
    met = approvals >= need.approvals and any(role_holds(need.role, r) for r in roles)
    found.append(
        PolicyCheck(
            "policy_met",
            met,
            {"approvals": approvals, "required": need.approvals, "role": need.role},
        )
    )
    return found
