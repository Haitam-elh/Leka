"""A person's decision on what LEKA proposes (LEKA-390), pure.

What these protect: the policy — one approval for a low or medium risk,
two for a high one, never the asker alone on a high one — kept as said,
refused when it cannot be (an unknown risk, a count out of range, a riskier
action needing fewer approvals); the risk decided at — the analysis's,
medium when it cannot say, at least medium in production; what is proposed
— the actions that change systems, once each, on what, where, within the
hard constraints, whether they can be undone; the tally — one rejection
rejects, one request for changes sends back, enough distinct approvers
approve, the asker not one of them when the policy says so, an earlier
revision's approvals not counted; who may vote; a modification — where it
runs, which actions are kept, never none.
"""

from __future__ import annotations

import uuid

import pytest

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

ASKER, ADA, BOB = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
BILLING = Target(uuid.uuid4(), "Billing API", "service")
D = DecisionStatus


def test_the_default_policy_wants_more_for_more_risk() -> None:
    assert DEFAULT_POLICY.requirement("low") == Requirement(1, separate=False)
    assert DEFAULT_POLICY.requirement("medium") == Requirement(1, separate=False)
    assert DEFAULT_POLICY.requirement("high") == Requirement(2, separate=True)
    kept = DEFAULT_POLICY.to_settings()
    assert kept == {
        "approvals": {"low": 1, "medium": 1, "high": 2},
        "separate": ["high"],
        "production_raises": True,
    }
    assert ApprovalPolicy.from_settings(kept) == DEFAULT_POLICY
    assert ApprovalPolicy.from_settings(None) == DEFAULT_POLICY


def test_a_policy_is_kept_as_said_or_refused() -> None:
    stricter = ApprovalPolicy.from_settings(
        {"approvals": {"medium": 2, "high": 3}, "separate": ["medium", "high"]}
    )
    assert stricter.requirement("medium") == Requirement(2, separate=True)
    assert stricter.requirement("low") == Requirement(1, separate=False)
    for wrong in (
        {"approvals": {"urgent": 1}},
        {"approvals": {"high": 0}},
        {"approvals": {"high": 6}},
        {"approvals": {"high": True}},
        {"approvals": {"medium": 3}},  # more than high's 2
        {"separate": ["sometimes"]},
        {"production_raises": "yes"},
        ["not", "an", "object"],
    ):
        with pytest.raises(PolicyError):
            ApprovalPolicy.from_settings(wrong)


def test_the_risk_decided_at() -> None:
    assert risk_of("high", "staging", DEFAULT_POLICY) == "high"
    assert risk_of("low", "staging", DEFAULT_POLICY) == "low"
    # In production, at least medium — unless the policy says otherwise.
    assert risk_of("low", "Production", DEFAULT_POLICY) == "medium"
    relaxed = ApprovalPolicy(production_raises=False)
    assert risk_of("low", "production", relaxed) == "low"
    # What LEKA cannot say is not low.
    assert risk_of("unknown", None, DEFAULT_POLICY) == "medium"
    assert risk_of(None, None, DEFAULT_POLICY) == "medium"


def test_what_is_proposed_is_what_changes_systems() -> None:
    proposals = proposals_of(
        [("restart", True), ("investigate", False), ("restart", True), ("migrate", True)],
        [BILLING],
        "production",
        [("no_downtime", True, True), ("services", ["x"], True), ("urgency", True, False)],
    )
    assert [(p.action, p.reversible) for p in proposals] == [("restart", True), ("migrate", False)]
    restart = proposals[0]
    assert (restart.targets, restart.environment) == ((BILLING,), "production")
    assert restart.constraints == (("no_downtime", True),)
    # Kept, and read back, the same.
    assert Proposal.from_dict(restart.as_dict()) == restart
    assert proposals_of([("investigate", False)], [BILLING], None) == ()


def _votes(*cast: tuple[Verdict, uuid.UUID, int]) -> list[Vote]:
    return [Vote(verdict, by, revision) for verdict, by, revision in cast]


def test_enough_distinct_approvers_approve_one_rejection_rejects() -> None:
    two = Requirement(2, separate=False)
    pending, approvers = tally(
        two, asker=ASKER, votes=_votes((Verdict.APPROVE, ADA, 1)), revision=1
    )
    assert (pending, approvers) == (D.PROPOSED, (ADA,))
    approved, approvers = tally(
        two,
        asker=ASKER,
        votes=_votes(
            (Verdict.APPROVE, ADA, 1), (Verdict.APPROVE, ADA, 1), (Verdict.APPROVE, BOB, 1)
        ),
        revision=1,
    )
    assert (approved, approvers) == (D.APPROVED, (ADA, BOB))
    rejected, _ = tally(
        two,
        asker=ASKER,
        votes=_votes((Verdict.APPROVE, ADA, 1), (Verdict.REJECT, BOB, 1)),
        revision=1,
    )
    assert rejected is D.REJECTED
    sent_back, _ = tally(
        two, asker=ASKER, votes=_votes((Verdict.REQUEST_CHANGES, BOB, 1)), revision=1
    )
    assert sent_back is D.CHANGES_REQUESTED


def test_the_asker_and_an_earlier_revision_do_not_count() -> None:
    four_eyes = Requirement(1, separate=True)
    alone, approvers = tally(
        four_eyes, asker=ASKER, votes=_votes((Verdict.APPROVE, ASKER, 1)), revision=1
    )
    assert (alone, approvers) == (D.PROPOSED, ())
    # Modified since: what was approved before is not what is decided now.
    stale, approvers = tally(
        Requirement(2, separate=False),
        asker=ASKER,
        votes=_votes((Verdict.APPROVE, BOB, 1), (Verdict.MODIFY, ADA, 2)),
        revision=2,
    )
    assert (stale, approvers) == (D.PROPOSED, (ADA,))


def test_who_may_vote() -> None:
    four_eyes = Requirement(1, separate=True)
    refused = may_vote(
        Verdict.APPROVE, by=ASKER, asker=ASKER, requirement=four_eyes, votes=[], revision=1
    )
    assert refused is not None and refused.code == "asker_may_not_approve"
    # The asker may still say no, or ask for changes.
    assert (
        may_vote(Verdict.REJECT, by=ASKER, asker=ASKER, requirement=four_eyes, votes=[], revision=1)
        is None
    )
    twice = may_vote(
        Verdict.APPROVE,
        by=ADA,
        asker=ASKER,
        requirement=Requirement(2, separate=False),
        votes=_votes((Verdict.APPROVE, ADA, 1)),
        revision=1,
    )
    assert twice is not None and twice.code == "already_approved"
    # A new revision may be approved again.
    assert (
        may_vote(
            Verdict.APPROVE,
            by=ADA,
            asker=ASKER,
            requirement=Requirement(2, separate=False),
            votes=_votes((Verdict.APPROVE, ADA, 1)),
            revision=2,
        )
        is None
    )


def test_a_modification_where_it_runs_and_what_is_kept() -> None:
    proposals = proposals_of([("restart", True), ("scale", True)], [BILLING], "production")
    staged = modified(proposals, Change(environment="staging"))
    assert [p.environment for p in staged] == ["staging", "staging"]
    assert environment_of(staged) == "staging"
    assert environment_of(proposals) == "production"
    only = modified(proposals, Change(keep=("scale",)))
    assert [p.action for p in only] == ["scale"]
    with pytest.raises(ValueError, match="At least one"):
        modified(proposals, Change(keep=()))
    with pytest.raises(ValueError, match="Not proposed: deploy"):
        modified(proposals, Change(keep=("deploy",)))
