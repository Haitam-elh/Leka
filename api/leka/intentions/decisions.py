"""A person's decision on what LEKA proposes (LEKA-390), and the policy
that governs it (LEKA-404), pure.

An intention that asks to act on systems is analysed (LEKA-388), then waits
for a decision: what it would do — each proposed action, on what, where,
within which constraints, whether it can be undone — how risky that is,
and who must approve it, said by the workspace's policy.

    proposed ──▶ approve, N times ──▶ approved (enough distinct approvers)
        │     ──▶ reject     ──▶ rejected      (one is enough: nothing runs)
        │     ──▶ ask changes ─▶ changes_requested (the asker asks again)
        └──── modify ──▶ the next revision: its risk read again, the
                         approvals before it void, the modifier's own
                         counting for the new one

THE RISK (LEKA-404). Four levels: low, medium, high, critical. The
analysis's risk — medium when it cannot say — raised by the policy's rules,
each that holds said: an action in production at least medium; one that
cannot be undone at least high, critical in production; one on something
critical in production at least high. A workspace adds its own rules: by
action, environment, the kind or criticality of what it acts on, whether it
can be undone.

THE REQUIREMENT, per level: how many distinct people approve; whether the
asker may be one of them (four eyes); a role one of them must hold (an
owner, for a critical one); how long an approval holds before the action
must run; after how long a decision waiting is escalated. By default one
approval for low and medium, two for high and critical, never the asker
on high or critical, an owner on critical. Kept in the workspace's
settings, changed by its admins.

A vote counts for the person whose authority it uses: theirs, or the one
who delegated theirs (governance.py). Every vote is kept with the context it
was cast in (approval.py): who, for whom, as which role, when, why, on which
revision, at which risk.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Any, cast

RISKS = ("low", "medium", "high", "critical")
RANK = {risk: rank for rank, risk in enumerate(RISKS)}
# Who may be required among the approvers, the least first: a role ranks
# what it requires and what is above it.
ROLES = ("admin", "owner")
ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}

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
    """What a decision needs: how many distinct approvers; whether the asker
    may be one of them; a role one of them must hold; how long an approval
    holds; after how long one waiting is escalated (hours)."""

    approvals: int
    separate: bool
    role: str | None = None
    valid_hours: int | None = None
    escalate_hours: int | None = None


PRODUCTION = frozenset({"production", "prod", "prd"})


def in_production(environment: str | None) -> bool:
    return environment is not None and environment.casefold() in PRODUCTION


@dataclass(frozen=True)
class RiskRule:
    """A rule that raises a decision's risk: when every condition it says
    holds of one proposed action — at least `at_least`. A condition left
    empty holds of anything."""

    name: str
    at_least: str
    actions: frozenset[str] = frozenset()
    # `production` means any of its names.
    environments: frozenset[str] = frozenset()
    target_types: frozenset[str] = frozenset()
    # How critical one of its targets is: critical, high…
    target_criticality: frozenset[str] = frozenset()
    reversible: bool | None = None

    def holds(self, proposal: Proposal, criticality: Mapping[uuid.UUID, str | None]) -> bool:
        if self.actions and proposal.action not in self.actions:
            return False
        if self.environments:
            where = (proposal.environment or "").casefold()
            names = {e.casefold() for e in self.environments}
            if not (where in names or ("production" in names and in_production(where))):
                return False
        if self.target_types and not any(t.type in self.target_types for t in proposal.targets):
            return False
        if self.target_criticality and not any(
            (criticality.get(t.id) or "") in self.target_criticality for t in proposal.targets
        ):
            return False
        return self.reversible is None or proposal.reversible is self.reversible

    def to_settings(self) -> dict[str, object]:
        said: dict[str, object] = {"name": self.name, "at_least": self.at_least}
        for key in ("actions", "environments", "target_types", "target_criticality"):
            if getattr(self, key):
                said[key] = sorted(getattr(self, key))
        if self.reversible is not None:
            said["reversible"] = self.reversible
        return said

    @classmethod
    def from_settings(cls, said: object) -> RiskRule:
        if not isinstance(said, Mapping):
            raise PolicyError("A rule is an object.")
        name = str(said.get("name") or "").strip()
        if not name or len(name) > 60:
            raise PolicyError("A rule has a name, 60 characters at most.")
        at_least = said.get("at_least")
        if at_least not in RANK:
            raise PolicyError(f"{name}: at_least is one of {', '.join(RISKS)}.")
        sets: dict[str, frozenset[str]] = {}
        for key in ("actions", "environments", "target_types", "target_criticality"):
            value = said.get(key) or []
            if not isinstance(value, list) or any(
                not isinstance(v, str) or not v.strip() for v in value
            ):
                raise PolicyError(f"{name}: {key} lists words.")
            sets[key] = frozenset(v.strip() for v in value[:30])
        reversible = said.get("reversible")
        if reversible is not None and not isinstance(reversible, bool):
            raise PolicyError(f"{name}: reversible is true, false, or left out.")
        return cls(name=name, at_least=str(at_least), reversible=reversible, **sets)


# The rules LEKA starts a workspace with.
DEFAULT_RULES = (
    RiskRule("irreversible", "high", reversible=False),
    RiskRule(
        "irreversible_in_production",
        "critical",
        environments=frozenset({"production"}),
        reversible=False,
    ),
    RiskRule(
        "critical_target_in_production",
        "high",
        environments=frozenset({"production"}),
        target_criticality=frozenset({"critical"}),
    ),
)


def _per_risk(
    said: object, name: str, default: Mapping[str, int | None], low: int, high: int
) -> dict[str, int | None]:
    """A number, or none, per risk — what is not said, the default's."""
    found = dict(default)
    if said is None:
        return found
    if not isinstance(said, Mapping):
        raise PolicyError(f"`{name}` is an object, by risk.")
    for risk, value in said.items():
        if risk not in RANK:
            raise PolicyError(f"Unknown risk: {risk}.")
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high
        ):
            raise PolicyError(f"`{name}`: between {low} and {high}, or none.")
        found[risk] = value
    return found


@dataclass(frozen=True)
class ApprovalPolicy:
    approvals: Mapping[str, int] = field(
        default_factory=lambda: {"low": 1, "medium": 1, "high": 2, "critical": 2}
    )
    # The risks on which the asker may not approve their own request.
    separate: frozenset[str] = frozenset({"high", "critical"})
    # An action in production is at least a medium risk.
    production_raises: bool = True
    # A role one approver must hold, per risk (LEKA-404).
    roles: Mapping[str, str | None] = field(
        default_factory=lambda: {"low": None, "medium": None, "high": None, "critical": "owner"}
    )
    # How long an approval holds: past it, the action must be approved again.
    valid_hours: Mapping[str, int | None] = field(
        default_factory=lambda: {"low": None, "medium": None, "high": 72, "critical": 24}
    )
    # After how long a decision still waiting is escalated to the owners.
    escalate_hours: Mapping[str, int | None] = field(
        default_factory=lambda: {"low": None, "medium": 48, "high": 24, "critical": 4}
    )
    rules: tuple[RiskRule, ...] = DEFAULT_RULES

    def requirement(self, risk: str) -> Requirement:
        return Requirement(
            approvals=self.approvals[risk],
            separate=risk in self.separate,
            role=self.roles.get(risk),
            valid_hours=self.valid_hours.get(risk),
            escalate_hours=self.escalate_hours.get(risk),
        )

    def to_settings(self) -> dict[str, object]:
        return {
            "approvals": {risk: self.approvals[risk] for risk in RISKS},
            "separate": sorted(self.separate, key=RANK.__getitem__),
            "production_raises": self.production_raises,
            "roles": {risk: self.roles.get(risk) for risk in RISKS},
            "valid_hours": {risk: self.valid_hours.get(risk) for risk in RISKS},
            "escalate_hours": {risk: self.escalate_hours.get(risk) for risk in RISKS},
            "rules": [rule.to_settings() for rule in self.rules],
        }

    @classmethod
    def from_settings(cls, said: object) -> ApprovalPolicy:
        """The workspace's policy as kept in its settings — the default for
        what it does not say (a policy kept before LEKA-404 included).
        PolicyError when what it says cannot be."""
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
        # Kept before critical was a risk: it needs at least what high does.
        if "critical" not in dict(said.get("approvals") or {}):
            approvals["critical"] = max(approvals["critical"], approvals["high"])
        separate = said.get("separate", sorted(base.separate))
        if not isinstance(separate, list) or any(r not in RANK for r in separate):
            raise PolicyError("`separate` lists risks: low, medium, high, critical.")
        if "separate" in said and "high" in separate and "critical" not in separate:
            # Kept before critical was a risk: what holds of high holds of it.
            separate = [*separate, "critical"]
        raises = said.get("production_raises", base.production_raises)
        if not isinstance(raises, bool):
            raise PolicyError("`production_raises` is true or false.")
        roles = dict(base.roles)
        for risk, role in dict(said.get("roles") or {}).items():
            if risk not in RANK:
                raise PolicyError(f"Unknown risk: {risk}.")
            if role is not None and role not in ROLES:
                raise PolicyError("A role required is admin or owner, or none.")
            roles[risk] = role
        valid = _per_risk(said.get("valid_hours"), "valid_hours", base.valid_hours, 1, 720)
        escalate = _per_risk(
            said.get("escalate_hours"), "escalate_hours", base.escalate_hours, 1, 720
        )
        rules_said = said.get("rules")
        if rules_said is None:
            rules = base.rules
        elif not isinstance(rules_said, list) or len(rules_said) > 30:
            raise PolicyError("`rules` lists 30 rules at most.")
        else:
            rules = tuple(RiskRule.from_settings(r) for r in rules_said)
            if len({r.name for r in rules}) != len(rules):
                raise PolicyError("Two rules share a name.")
        # A riskier action never needs fewer approvals than a safer one.
        if any(approvals[a] > approvals[b] for a, b in pairwise(RISKS)):
            raise PolicyError("A higher risk cannot need fewer approvals than a lower one.")
        return cls(
            approvals=approvals,
            separate=frozenset(separate),
            production_raises=raises,
            roles=roles,
            valid_hours=valid,
            escalate_hours=escalate,
            rules=rules,
        )


DEFAULT_POLICY = ApprovalPolicy()


@dataclass(frozen=True)
class Reason:
    """Why a decision is at its risk: what raised it, with its values."""

    code: str
    params: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "params": dict(self.params)}


def classify(
    said: str | None,
    proposals: Sequence[Proposal],
    policy: ApprovalPolicy,
    criticality: Mapping[uuid.UUID, str | None] | None = None,
) -> tuple[str, tuple[Reason, ...]]:
    """The risk a decision is taken at, and why: the analysis's — medium
    when it cannot say — raised by every rule that holds of one of its
    actions, the highest winning."""
    known = criticality or {}
    risk = said if said in RANK else "medium"
    reasons = [Reason("analysis", {"risk": said}) if said in RANK else Reason("unknown")]

    def raise_to(level: str, reason: Reason) -> None:
        nonlocal risk
        if RANK[level] > RANK[risk]:
            risk = level
            reasons.append(reason)

    if policy.production_raises and any(in_production(p.environment) for p in proposals):
        raise_to("medium", Reason("production"))
    for rule in policy.rules:
        held = [p for p in proposals if rule.holds(p, known)]
        if held:
            raise_to(
                rule.at_least,
                Reason(
                    "rule",
                    {"rule": rule.name, "action": held[0].action, "at_least": rule.at_least},
                ),
            )
    return risk, tuple(reasons)


def risk_of(said: str | None, environment: str | None, policy: ApprovalPolicy) -> str:
    """The risk of an action somewhere, under a policy — as classify says it
    of one action LEKA knows nothing more of."""
    probe = Proposal(id="probe", action="", targets=(), environment=environment)
    return classify(said, [probe], policy)[0]


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
    # Cast with another's authority, delegated to `by` (LEKA-404).
    on_behalf_of: uuid.UUID | None = None
    # The role of the authority used, when it was cast.
    role: str | None = None

    @property
    def authority(self) -> uuid.UUID:
        """Whose approval it is: the one who delegated, or the voter."""
        return self.on_behalf_of or self.by


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
    on_behalf_of: uuid.UUID | None = None,
) -> Refusal | None:
    """Whether this person may cast this vote now — None when they may. The
    asker approves neither their own request nor for someone else, when the
    policy keeps them apart; an authority approves once."""
    authority = on_behalf_of or by
    if (
        verdict in APPROVING
        and requirement.separate
        and asker is not None
        and asker in (by, authority)
    ):
        return Refusal("asker_may_not_approve")
    if verdict is Verdict.APPROVE and any(
        v.authority == authority and v.revision == revision and v.verdict in APPROVING
        for v in votes
    ):
        return Refusal("already_approved")
    return None


def role_holds(required: str | None, held: str | None) -> bool:
    """Whether a role meets the role required: the same, or above it."""
    if required is None:
        return True
    return ROLE_RANK.get(held or "", -1) >= ROLE_RANK.get(required, 99)


def tally(
    requirement: Requirement,
    *,
    asker: uuid.UUID | None,
    votes: Sequence[Vote],
    revision: int,
) -> tuple[DecisionStatus, tuple[uuid.UUID, ...]]:
    """Where a decision stands after its votes on its current revision: one
    rejection rejects it, one request for changes sends it back, enough
    distinct authorities approve it — one of them holding the role it
    requires — and who they are, in order."""
    current = [v for v in votes if v.revision == revision]
    if any(v.verdict is Verdict.REJECT for v in current):
        return DecisionStatus.REJECTED, ()
    if any(v.verdict is Verdict.REQUEST_CHANGES for v in current):
        return DecisionStatus.CHANGES_REQUESTED, ()
    counted = [
        v
        for v in current
        if v.verdict in APPROVING
        and not (requirement.separate and asker is not None and asker in (v.by, v.authority))
    ]
    approvers = tuple(dict.fromkeys(v.authority for v in counted))
    role = any(role_holds(requirement.role, v.role) for v in counted)
    if len(approvers) >= requirement.approvals and role:
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
