"""A person's decision on what LEKA proposes (LEKA-390), pure.

An intention that asks to act on systems is analysed (LEKA-388), then waits
for a decision: what it would do — each proposed action, on what, where,
within which constraints, whether it can be undone — how risky that is,
and how many people must approve it, said by the workspace's policy.

    proposed ──▶ approve, N times ──▶ approved (enough distinct approvers)
        │     ──▶ reject     ──▶ rejected      (one is enough: nothing runs)
        │     ──▶ ask changes ─▶ changes_requested (the asker asks again)
        └──── modify ──▶ the next revision: its risk read again, the
                         approvals before it void, the modifier's own
                         counting for the new one

THE POLICY. Per risk, how many distinct people must approve, and whether
the asker may be one of them (`separate`: four eyes). By default one for a
low or medium risk, two for a high one, never the asker alone on a high
one; an action in production is at least medium; a risk LEKA cannot say is
medium — kept in the workspace's settings, changed by its admins.

Every vote is kept with the context it was cast in (approval.py): who,
when, why, on which revision, at which risk, from which analysis.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Any, cast

RISKS = ("low", "medium", "high")
RANK = {risk: rank for rank, risk in enumerate(RISKS)}

# What an action does to a running system can be undone by another action
# — restarted, rolled back, scaled back — or not, or LEKA cannot say.
REVERSIBLE: Mapping[str, bool] = {
    "restart": True,
    "rollback": True,
    "deploy": True,
    "scale": True,
    "stop": True,
    "update": True,
    "fix": True,
    "migrate": False,
}


class DecisionStatus(enum.StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    # Asked again, cancelled, or a newer decision opened: no longer the one.
    SUPERSEDED = "superseded"


class Verdict(enum.StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"
    REQUEST_CHANGES = "request_changes"


APPROVING = frozenset({Verdict.APPROVE, Verdict.MODIFY})


class PolicyError(ValueError):
    """A policy that cannot be kept: an unknown risk, a count out of range."""


@dataclass(frozen=True)
class Requirement:
    """What a decision needs: how many distinct approvers, and whether the
    asker may be one of them."""

    approvals: int
    separate: bool


@dataclass(frozen=True)
class ApprovalPolicy:
    approvals: Mapping[str, int] = field(default_factory=lambda: {"low": 1, "medium": 1, "high": 2})
    # The risks on which the asker may not approve their own request.
    separate: frozenset[str] = frozenset({"high"})
    # An action in production is at least a medium risk.
    production_raises: bool = True

    def requirement(self, risk: str) -> Requirement:
        return Requirement(approvals=self.approvals[risk], separate=risk in self.separate)

    def to_settings(self) -> dict[str, object]:
        return {
            "approvals": {risk: self.approvals[risk] for risk in RISKS},
            "separate": sorted(self.separate, key=RANK.__getitem__),
            "production_raises": self.production_raises,
        }

    @classmethod
    def from_settings(cls, said: object) -> ApprovalPolicy:
        """The workspace's policy as kept in its settings — the default for
        what it does not say. PolicyError when what it says cannot be."""
        if said is None:
            return cls()
        if not isinstance(said, Mapping):
            raise PolicyError("The approval policy must be an object.")
        base = cls()
        approvals = dict(base.approvals)
        for risk, count in dict(said.get("approvals") or {}).items():
            if risk not in RANK:
                raise PolicyError(f"Unknown risk: {risk}.")
            if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 5:
                raise PolicyError("Each risk needs between 1 and 5 approvals.")
            approvals[risk] = count
        separate = said.get("separate", sorted(base.separate))
        if not isinstance(separate, list) or any(r not in RANK for r in separate):
            raise PolicyError("`separate` lists risks: low, medium, high.")
        raises = said.get("production_raises", base.production_raises)
        if not isinstance(raises, bool):
            raise PolicyError("`production_raises` is true or false.")
        # A riskier action never needs fewer approvals than a safer one.
        if any(approvals[a] > approvals[b] for a, b in pairwise(RISKS)):
            raise PolicyError("A higher risk cannot need fewer approvals than a lower one.")
        return cls(approvals=approvals, separate=frozenset(separate), production_raises=raises)


DEFAULT_POLICY = ApprovalPolicy()

PRODUCTION = frozenset({"production", "prod", "prd"})


def risk_of(said: str | None, environment: str | None, policy: ApprovalPolicy) -> str:
    """The risk a decision is taken at: the analysis's — medium when it
    cannot say — at least medium in production when the policy says so."""
    risk = said if said in RANK else "medium"
    if (
        policy.production_raises
        and environment is not None
        and environment.casefold() in PRODUCTION
        and RANK[risk] < RANK["medium"]
    ):
        risk = "medium"
    return risk


@dataclass(frozen=True)
class Target:
    id: uuid.UUID
    name: str
    type: str


@dataclass(frozen=True)
class Proposal:
    """One action proposed: what, on what, where, within which constraints,
    and whether it can be undone."""

    id: str
    action: str
    targets: tuple[Target, ...]
    environment: str | None
    constraints: tuple[tuple[str, object], ...] = ()
    reversible: bool | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "action": self.action,
            "targets": [{"id": str(t.id), "name": t.name, "type": t.type} for t in self.targets],
            "environment": self.environment,
            "constraints": [{"kind": k, "value": v} for k, v in self.constraints],
            "reversible": self.reversible,
        }

    @classmethod
    def from_dict(cls, said: Mapping[str, object]) -> Proposal:
        """As kept in a decision's `proposals` (as_dict)."""
        targets = cast("list[dict[str, Any]]", said.get("targets") or [])
        constraints = cast("list[dict[str, Any]]", said.get("constraints") or [])
        reversible = said.get("reversible")
        return cls(
            id=str(said["id"]),
            action=str(said["action"]),
            targets=tuple(
                Target(uuid.UUID(str(t["id"])), str(t["name"]), str(t["type"])) for t in targets
            ),
            environment=None if said.get("environment") is None else str(said["environment"]),
            constraints=tuple((str(c["kind"]), c.get("value")) for c in constraints),
            reversible=reversible if isinstance(reversible, bool) else None,
        )


def proposals_of(
    actions: Iterable[tuple[str, bool]],
    targets: Sequence[Target],
    environment: str | None,
    constraints: Iterable[tuple[str, object, bool]] = (),
) -> tuple[Proposal, ...]:
    """What an intention asks to do to systems, one proposal per action —
    on what it is about, where, within its hard constraints."""
    held = tuple(
        (kind, value)
        for kind, value, hard in constraints
        if hard and kind not in ("services", "sources")
    )
    return tuple(
        Proposal(
            id=code,
            action=code,
            targets=tuple(targets),
            environment=environment,
            constraints=held,
            reversible=REVERSIBLE.get(code),
        )
        for code, changes in dict.fromkeys(actions)
        if changes
    )


@dataclass(frozen=True)
class Vote:
    verdict: Verdict
    by: uuid.UUID
    revision: int


@dataclass(frozen=True)
class Refusal:
    """Why a vote cannot be cast: its code, for the interface to say."""

    code: str


def may_vote(
    verdict: Verdict,
    *,
    by: uuid.UUID,
    asker: uuid.UUID | None,
    requirement: Requirement,
    votes: Sequence[Vote],
    revision: int,
) -> Refusal | None:
    """Whether this person may cast this vote now — None when they may."""
    if verdict in APPROVING and requirement.separate and asker is not None and by == asker:
        return Refusal("asker_may_not_approve")
    if verdict is Verdict.APPROVE and any(
        v.by == by and v.revision == revision and v.verdict in APPROVING for v in votes
    ):
        return Refusal("already_approved")
    return None


def tally(
    requirement: Requirement,
    *,
    asker: uuid.UUID | None,
    votes: Sequence[Vote],
    revision: int,
) -> tuple[DecisionStatus, tuple[uuid.UUID, ...]]:
    """Where a decision stands after its votes on its current revision: one
    rejection rejects it, one request for changes sends it back, enough
    distinct approvers approve it — and who they are, in order."""
    current = [v for v in votes if v.revision == revision]
    if any(v.verdict is Verdict.REJECT for v in current):
        return DecisionStatus.REJECTED, ()
    if any(v.verdict is Verdict.REQUEST_CHANGES for v in current):
        return DecisionStatus.CHANGES_REQUESTED, ()
    approvers = tuple(
        dict.fromkeys(
            v.by
            for v in current
            if v.verdict in APPROVING and not (requirement.separate and v.by == asker)
        )
    )
    if len(approvers) >= requirement.approvals:
        return DecisionStatus.APPROVED, approvers
    return DecisionStatus.PROPOSED, approvers


@dataclass(frozen=True)
class Change:
    """What a person changes before approving: where it runs, and which of
    the proposed actions are kept."""

    environment: str | None = None
    keep: tuple[str, ...] | None = None


def modified(proposals: Sequence[Proposal], change: Change) -> tuple[Proposal, ...]:
    """The proposals as changed. ValueError when nothing would be left, or
    an action kept was never proposed."""
    known = {p.id for p in proposals}
    keep = known if change.keep is None else set(change.keep)
    if not keep:
        raise ValueError("At least one proposed action must be kept.")
    if keep - known:
        raise ValueError(f"Not proposed: {', '.join(sorted(keep - known))}.")
    return tuple(
        replace(p, environment=change.environment) if change.environment is not None else p
        for p in proposals
        if p.id in keep
    )


def environment_of(proposals: Sequence[Proposal]) -> str | None:
    """Where they would run: the riskiest environment among them."""
    found = [p.environment for p in proposals if p.environment]
    production = [e for e in found if e.casefold() in PRODUCTION]
    return production[0] if production else (found[0] if found else None)
