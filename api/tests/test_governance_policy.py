"""The governance of consequential actions (LEKA-404), pure.

What these protect: the risk classified to four levels, every reason said —
the analysis's, production, an action that cannot be undone, something
critical in production, a workspace's own rule; per risk what a decision
needs — approvals, the asker apart, a role; a vote counted for the authority
it uses — the voter's, or a delegation's that holds now, at that risk,
never one's own; exceptions granted only as they may be — a waiver names
its actions and environments, never above a medium risk, 90 days at most —
a freeze stopping what it covers, a waiver approving in advance what it
covers wholly, a freeze winning over a waiver; escalation once, after the
requirement's hours; before an action runs, no freeze, the approval not
expired, today's policy met, or the waiver not revoked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from leka.intentions.decisions import (
    DEFAULT_POLICY,
    ApprovalPolicy,
    DecisionStatus,
    Proposal,
    RiskRule,
    Target,
    Verdict,
    Vote,
    classify,
    may_vote,
    role_holds,
    tally,
)
from leka.intentions.governance import (
    Delegation,
    GovernanceError,
    GovernanceException,
    Scope,
    authority_of,
    checked_delegation,
    checked_exception,
    escalation_due,
    evaluate,
    freezes_of,
    policy_checks,
)

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
ASKER, ADA, BOB, OWEN = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
BILLING = Target(uuid.uuid4(), "Billing API", "service")
LEDGER = Target(uuid.uuid4(), "ledger", "database")
D = DecisionStatus


def _proposal(
    action: str,
    environment: str | None = "production",
    targets: tuple[Target, ...] = (BILLING,),
    reversible: bool | None = True,
) -> Proposal:
    return Proposal(
        id=action,
        action=action,
        targets=targets,
        environment=environment,
        reversible=reversible,
    )


def _codes(reasons: tuple[object, ...]) -> list[str]:
    return [r.code for r in reasons]  # type: ignore[attr-defined]


def _exception(
    kind: str,
    *,
    actions: tuple[str, ...] = (),
    environments: tuple[str, ...] = (),
    targets: tuple[uuid.UUID, ...] = (),
    max_risk: str = "low",
    starts: timedelta = timedelta(hours=-1),
    lasts: timedelta = timedelta(days=2),
    revoked: bool = False,
    by: uuid.UUID | None = ADA,
) -> GovernanceException:
    return GovernanceException(
        id=uuid.uuid4(),
        kind=kind,
        scope=Scope(frozenset(actions), frozenset(environments), frozenset(targets)),
        starts_at=NOW + starts,
        ends_at=NOW + starts + lasts,
        reason="Clôture comptable" if kind == "freeze" else "Redémarrages de routine",
        granted_by=by,
        max_risk=max_risk,
        revoked_at=NOW if revoked else None,
    )


# ── the risk ────────────────────────────────────────────────────────────────


def test_the_risk_is_classified_and_every_reason_said() -> None:
    restart_staging = _proposal("restart", "staging")
    risk, reasons = classify("low", [restart_staging], DEFAULT_POLICY)
    assert (risk, _codes(reasons)) == ("low", ["analysis"])
    assert reasons[0].params == {"risk": "low"}
    # What LEKA cannot say is not low.
    risk, reasons = classify(None, [restart_staging], DEFAULT_POLICY)
    assert (risk, _codes(reasons)) == ("medium", ["unknown"])
    # In production, at least medium.
    risk, reasons = classify("low", [_proposal("restart")], DEFAULT_POLICY)
    assert (risk, _codes(reasons)) == ("medium", ["analysis", "production"])
    # What cannot be undone: high; in production, critical.
    risk, reasons = classify(
        "low", [_proposal("migrate", "staging", reversible=False)], DEFAULT_POLICY
    )
    assert (risk, _codes(reasons)) == ("high", ["analysis", "rule"])
    assert reasons[-1].params == {"rule": "irreversible", "action": "migrate", "at_least": "high"}
    risk, reasons = classify(
        "low", [_proposal("restart"), _proposal("migrate", reversible=False)], DEFAULT_POLICY
    )
    assert risk == "critical"
    assert [r.params.get("rule") for r in reasons if r.code == "rule"] == [
        "irreversible",
        "irreversible_in_production",
    ]
    # Something critical, in production: high.
    risk, reasons = classify(
        "medium", [_proposal("restart")], DEFAULT_POLICY, {BILLING.id: "critical"}
    )
    assert (risk, reasons[-1].params["rule"]) == ("high", "critical_target_in_production")
    assert (
        classify(
            "medium", [_proposal("restart", "staging")], DEFAULT_POLICY, {BILLING.id: "critical"}
        )[0]
        == "medium"
    )
    # A risk is never lowered: the analysis's high stays high.
    assert classify("high", [_proposal("restart", "staging")], DEFAULT_POLICY)[0] == "high"


def test_a_workspace_adds_its_own_rules() -> None:
    policy = ApprovalPolicy.from_settings(
        {
            "rules": [
                {"name": "databases", "at_least": "high", "target_types": ["database"]},
                {
                    "name": "prod_scale",
                    "at_least": "critical",
                    "actions": ["scale"],
                    "environments": ["production"],
                },
            ]
        }
    )
    # Its rules replace LEKA's: what cannot be undone no longer raises it.
    assert classify("low", [_proposal("migrate", "staging", reversible=False)], policy)[0] == "low"
    assert classify("low", [_proposal("restart", "staging", (LEDGER,))], policy)[0] == "high"
    # `production` holds of any of its names.
    assert classify("low", [_proposal("scale", "prd")], policy)[0] == "critical"
    assert classify("low", [_proposal("scale", "staging")], policy)[0] == "low"
    # Kept, and read back, the same.
    assert ApprovalPolicy.from_settings(policy.to_settings()) == policy
    rule = RiskRule.from_settings({"name": "n", "at_least": "high", "reversible": False})
    assert RiskRule.from_settings(rule.to_settings()) == rule


# ── approvals, roles, delegation ────────────────────────────────────────────


def test_a_critical_decision_waits_for_an_owner() -> None:
    need = DEFAULT_POLICY.requirement("critical")
    two_admins = [
        Vote(Verdict.APPROVE, ADA, 1, role="admin"),
        Vote(Verdict.APPROVE, BOB, 1, role="admin"),
    ]
    assert tally(need, asker=ASKER, votes=two_admins, revision=1) == (D.PROPOSED, (ADA, BOB))
    with_owner = [*two_admins, Vote(Verdict.APPROVE, OWEN, 1, role="owner")]
    assert tally(need, asker=ASKER, votes=with_owner, revision=1)[0] is D.APPROVED
    # A role ranks what it requires and what is above it.
    assert role_holds("admin", "owner")
    assert not role_holds("owner", "admin")
    assert not role_holds("admin", None)
    assert role_holds(None, None)


def test_a_delegated_vote_counts_once_for_whose_authority_it_is() -> None:
    need = DEFAULT_POLICY.requirement("high")
    # Bob votes for Ada: it is Ada's approval, kept as both.
    votes = [Vote(Verdict.APPROVE, BOB, 1, on_behalf_of=ADA, role="admin")]
    assert tally(need, asker=ASKER, votes=votes, revision=1) == (D.PROPOSED, (ADA,))
    # Ada cannot approve a second time through Bob, nor Bob for her twice.
    refused = may_vote(
        Verdict.APPROVE, by=ADA, asker=ASKER, requirement=need, votes=votes, revision=1
    )
    assert refused is not None
    assert refused.code == "already_approved"
    # The asker approves neither for themselves nor for someone else.
    for by, on_behalf_of in ((ASKER, ADA), (BOB, ASKER)):
        refused = may_vote(
            Verdict.APPROVE,
            by=by,
            asker=ASKER,
            requirement=need,
            votes=[],
            revision=1,
            on_behalf_of=on_behalf_of,
        )
        assert refused is not None
        assert refused.code == "asker_may_not_approve"
    both = [*votes, Vote(Verdict.APPROVE, OWEN, 1, role="owner")]
    assert tally(need, asker=ASKER, votes=both, revision=1) == (D.APPROVED, (ADA, OWEN))


def test_a_delegation_holds_for_its_time_its_risk_its_person() -> None:
    lent = Delegation(
        id=uuid.uuid4(),
        by=ADA,
        to=BOB,
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(days=7),
        max_risk="high",
        reason="Congés",
    )
    assert authority_of(BOB, ADA, [lent], "high", NOW) == lent
    assert authority_of(BOB, ADA, [lent], "critical", NOW) is None
    assert authority_of(OWEN, ADA, [lent], "low", NOW) is None
    assert authority_of(BOB, OWEN, [lent], "low", NOW) is None
    assert authority_of(BOB, None, [lent], "low", NOW) is None
    assert authority_of(BOB, ADA, [lent], "low", NOW + timedelta(days=8)) is None
    revoked = Delegation(**{**lent.__dict__, "revoked_at": NOW})
    assert authority_of(BOB, ADA, [revoked], "low", NOW) is None
    with pytest.raises(GovernanceError):
        checked_delegation(Delegation(**{**lent.__dict__, "to": ADA}))
    with pytest.raises(GovernanceError):
        checked_delegation(Delegation(**{**lent.__dict__, "ends_at": NOW + timedelta(days=91)}))
    with pytest.raises(GovernanceError):
        checked_delegation(Delegation(**{**lent.__dict__, "max_risk": "urgent"}))
    with pytest.raises(GovernanceError):
        checked_delegation(Delegation(**{**lent.__dict__, "reason": "  "}))
    assert checked_delegation(lent) == lent


# ── exceptions ──────────────────────────────────────────────────────────────


def test_an_exception_is_granted_only_as_it_may_be() -> None:
    assert checked_exception(_exception("freeze"))  # a freeze on everything
    assert checked_exception(
        _exception("waiver", actions=("restart",), environments=("staging",), max_risk="medium")
    )
    for wrong in (
        _exception("pause"),
        # A waiver names what it waives, where.
        _exception("waiver", actions=("restart",)),
        _exception("waiver", environments=("staging",)),
        # Never what is high or critical.
        _exception("waiver", actions=("restart",), environments=("staging",), max_risk="high"),
        _exception("freeze", lasts=timedelta(days=91)),
        _exception("freeze", lasts=timedelta(0)),
    ):
        with pytest.raises(GovernanceError):
            checked_exception(wrong)


def test_a_freeze_stops_what_it_covers_and_wins_over_a_waiver() -> None:
    freeze = _exception("freeze", environments=("production",))
    said = evaluate(
        [_proposal("restart", "prod")],
        analysis_risk="low",
        policy=DEFAULT_POLICY,
        exceptions=[freeze],
        now=NOW,
    )
    assert said.frozen
    assert said.frozen_by == (freeze.id,)
    assert said.exceptions[0]["reason"] == "Clôture comptable"
    # Not what it does not cover; not before it starts, after it ends, once revoked.
    assert not evaluate(
        [_proposal("restart", "staging")],
        analysis_risk="low",
        policy=DEFAULT_POLICY,
        exceptions=[freeze],
        now=NOW,
    ).frozen
    for idle in (
        _exception("freeze", starts=timedelta(hours=1)),
        _exception("freeze", starts=timedelta(days=-3)),
        _exception("freeze", revoked=True),
    ):
        assert not freezes_of([_proposal("restart")], [idle], NOW)
    # On a thing: only what acts on it.
    on_ledger = _exception("freeze", targets=(LEDGER.id,))
    assert freezes_of([_proposal("restart", targets=(BILLING, LEDGER))], [on_ledger], NOW)
    assert not freezes_of([_proposal("restart")], [on_ledger], NOW)
    # Frozen and waived: frozen.
    waiver = _exception(
        "waiver", actions=("restart",), environments=("production",), max_risk="medium"
    )
    both = evaluate(
        [_proposal("restart")],
        analysis_risk="low",
        policy=DEFAULT_POLICY,
        exceptions=[freeze, waiver],
        now=NOW,
    )
    assert both.frozen
    assert both.waived_by is None


def test_a_waiver_approves_in_advance_only_what_it_wholly_covers() -> None:
    waiver = _exception(
        "waiver", actions=("restart",), environments=("production",), max_risk="medium"
    )

    def waived(
        *proposals: Proposal, risk: str = "low", exception: GovernanceException = waiver
    ) -> bool:
        said = evaluate(
            list(proposals),
            analysis_risk=risk,
            policy=DEFAULT_POLICY,
            exceptions=[exception],
            now=NOW,
        )
        return said.waived_by == exception.id and said.approved_by == exception.granted_by

    assert waived(_proposal("restart"))
    # Not a high risk: an analysis's, or a rule's.
    assert not waived(_proposal("restart"), risk="high")
    assert not waived(_proposal("restart", reversible=False))
    # Not when one of the actions is not covered.
    assert not waived(_proposal("restart"), _proposal("scale"))
    assert not waived(_proposal("restart", "staging"))
    # Not once its grantor is gone: their approval is what it gives.
    orphan = _exception(
        "waiver", actions=("restart",), environments=("production",), max_risk="medium", by=None
    )
    assert not waived(_proposal("restart"), exception=orphan)


# ── escalation ──────────────────────────────────────────────────────────────


def test_a_decision_waiting_is_escalated_once_after_its_hours() -> None:
    need = DEFAULT_POLICY.requirement("critical")
    assert need.escalate_hours == 4
    created = NOW - timedelta(hours=3)
    assert not escalation_due(created, need, NOW, escalated_at=None)
    assert escalation_due(created, need, NOW + timedelta(hours=1), escalated_at=None)
    assert not escalation_due(created, need, NOW + timedelta(hours=1), escalated_at=NOW)
    assert not escalation_due(
        created, DEFAULT_POLICY.requirement("low"), NOW + timedelta(days=30), escalated_at=None
    )
    said = evaluate([_proposal("restart")], analysis_risk="low", policy=DEFAULT_POLICY, now=NOW)
    assert said.escalate_at == NOW + timedelta(hours=48)


# ── before an action runs ───────────────────────────────────────────────────


def _checks(**given: object) -> dict[str, bool]:
    said: dict[str, object] = {
        "risk": "high",
        "valid_until": NOW + timedelta(hours=1),
        "approvals": 2,
        "roles": ["admin", "owner"],
        "policy": DEFAULT_POLICY,
        "exceptions": [],
        "now": NOW,
    }
    said.update(given)
    found = policy_checks([_proposal("restart")], **said)  # type: ignore[arg-type]
    return {c.code: c.passed for c in found}


def test_what_the_policy_says_before_an_action_runs() -> None:
    assert _checks() == {"not_frozen": True, "approval_valid": True, "policy_met": True}
    assert _checks(exceptions=[_exception("freeze")])["not_frozen"] is False
    assert _checks(now=NOW + timedelta(hours=2))["approval_valid"] is False
    assert "approval_valid" not in _checks(valid_until=None)
    # Tightened since it was approved: asked again.
    tighter = ApprovalPolicy.from_settings({"approvals": {"high": 3}})
    assert _checks(policy=tighter)["policy_met"] is False
    # An approver no longer allowed: fewer approvals than it needs.
    assert _checks(approvals=1, roles=["admin"])["policy_met"] is False
    # A critical one whose owner is no longer one.
    assert _checks(risk="critical", roles=["admin", "admin"])["policy_met"] is False
    assert _checks(risk="critical")["policy_met"] is True
    # Approved by a waiver: the waiver must still hold.
    assert _checks(waived=True, approvals=1) == {
        "not_frozen": True,
        "approval_valid": True,
        "waiver_holds": True,
    }
    assert _checks(waived=False)["waiver_holds"] is False
