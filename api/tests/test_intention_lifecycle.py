"""An intention's lifecycle (LEKA-384), pure.

What these protect: the path from asking to verifying, each step by whom
it is allowed — an approval or a rejection is a person's, never LEKA's;
what LEKA concludes, runs and checks is LEKA's; cancelling until actions
run, never after; cancelled is final, the rest may be asked again; every
state in exactly one phase of the list; a move the lifecycle does not have
refused, said with where it was and who tried.
"""

from __future__ import annotations

import pytest

from leka.intentions import (
    CLOSED,
    PHASES,
    TRANSITIONS,
    Actor,
    IllegalTransitionError,
    IntentionStatus,
    moves,
    phase,
)
from leka.intentions.lifecycle import move

S = IntentionStatus
P, SYS = Actor.PERSON, Actor.SYSTEM

# The way an intention goes when it is acted on, and who moves it.
HAPPY = [
    (S.SUBMITTED, S.ANALYSING, SYS, "analysis_started"),
    (S.ANALYSING, S.AWAITING_DECISION, SYS, "proposed"),
    (S.AWAITING_DECISION, S.APPROVED, P, "approved"),
    (S.APPROVED, S.SCHEDULED, P, "scheduled"),
    (S.SCHEDULED, S.EXECUTING, SYS, "execution_started"),
    (S.EXECUTING, S.VERIFYING, SYS, "executed"),
    (S.VERIFYING, S.COMPLETED, SYS, "verified"),
]


@pytest.mark.parametrize(("at", "to", "by", "name"), HAPPY)
def test_the_way_from_asking_to_verified(
    at: IntentionStatus, to: IntentionStatus, by: Actor, name: str
) -> None:
    assert move(at, to, by).name == name


def test_a_question_answered_needs_no_decision() -> None:
    assert move(S.ANALYSING, S.COMPLETED, SYS).name == "answered"


@pytest.mark.parametrize("to", [S.APPROVED, S.REJECTED])
def test_a_decision_is_a_persons_never_leka_s(to: IntentionStatus) -> None:
    assert move(S.AWAITING_DECISION, to, P).to is to
    with pytest.raises(IllegalTransitionError) as refused:
        move(S.AWAITING_DECISION, to, SYS)
    assert (refused.value.at, refused.value.to, refused.value.by) == (S.AWAITING_DECISION, to, SYS)


@pytest.mark.parametrize(
    ("at", "to"),
    [
        (S.SUBMITTED, S.ANALYSING),
        (S.ANALYSING, S.AWAITING_DECISION),
        (S.EXECUTING, S.VERIFYING),
    ],
)
def test_what_leka_concludes_and_runs_is_leka_s(at: IntentionStatus, to: IntentionStatus) -> None:
    with pytest.raises(IllegalTransitionError):
        move(at, to, P)


def test_nothing_is_approved_before_it_is_analysed_nor_run_before_approved() -> None:
    for at, to in (
        (S.SUBMITTED, S.APPROVED),
        (S.ANALYSING, S.APPROVED),
        (S.AWAITING_DECISION, S.EXECUTING),
        (S.SUBMITTED, S.EXECUTING),
        (S.REJECTED, S.EXECUTING),
        (S.ANALYSING, S.VERIFYING),
    ):
        for actor in Actor:
            with pytest.raises(IllegalTransitionError):
                move(at, to, actor)


def test_cancelled_by_a_person_until_its_actions_run() -> None:
    cancellable = {
        S.SUBMITTED,
        S.NEEDS_CLARIFICATION,
        S.ANALYSING,
        S.AWAITING_DECISION,
        S.APPROVED,
        S.SCHEDULED,
        S.FAILED,
    }
    for status in IntentionStatus:
        can = any(m.to is S.CANCELLED and P in m.by for m in moves(status))
        assert can is (status in cancellable), status
    with pytest.raises(IllegalTransitionError):
        move(S.ANALYSING, S.CANCELLED, SYS)


def test_cancelled_is_final_the_rest_may_be_asked_again() -> None:
    assert moves(S.CANCELLED) == ()
    for status in (S.COMPLETED, S.REJECTED, S.AWAITING_DECISION, S.ANALYSING):
        assert move(status, S.ANALYSING, P).name == "asked_again"
    assert move(S.FAILED, S.ANALYSING, P).name == "retried"
    assert move(S.FAILED, S.EXECUTING, SYS).name == "retried"


def test_what_is_not_understood_is_asked_and_clarified_by_asking_again() -> None:
    """LEKA-385: LEKA flags what it cannot understand; a person clarifies."""
    for at in (S.SUBMITTED, S.ANALYSING):
        assert move(at, S.NEEDS_CLARIFICATION, SYS).name == "clarification_asked"
        with pytest.raises(IllegalTransitionError):
            move(at, S.NEEDS_CLARIFICATION, P)
    assert move(S.NEEDS_CLARIFICATION, S.ANALYSING, P).name == "clarified"
    with pytest.raises(IllegalTransitionError):
        move(S.NEEDS_CLARIFICATION, S.ANALYSING, SYS)
    # Nothing is decided on what was not understood.
    for to in (S.AWAITING_DECISION, S.APPROVED, S.EXECUTING):
        for actor in Actor:
            with pytest.raises(IllegalTransitionError):
                move(S.NEEDS_CLARIFICATION, to, actor)
    assert phase(S.NEEDS_CLARIFICATION) == "active"


def test_what_fails_is_said_failed_by_leka() -> None:
    for at in (S.SUBMITTED, S.ANALYSING, S.EXECUTING, S.VERIFYING):
        assert move(at, S.FAILED, SYS).name == "failed"


def test_every_state_is_in_exactly_one_phase() -> None:
    for status in IntentionStatus:
        assert sum(status in states for states in PHASES.values()) == 1, status
    assert phase(S.SCHEDULED) == "scheduled"
    assert phase(S.FAILED) == "active"
    assert {s for s in IntentionStatus if phase(s) == "finished"} == CLOSED


def test_every_state_is_declared_and_every_move_leads_somewhere_declared() -> None:
    assert set(TRANSITIONS) == set(IntentionStatus)
    for found in TRANSITIONS.values():
        for candidate in found:
            assert candidate.to in IntentionStatus
            assert candidate.by
            assert candidate.name
