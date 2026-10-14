"""An intention's journey (LEKA-443), pure: where it stands as a person reads
it — the same state on every screen — read from what was kept.

What these protect:
- Each lifecycle state reads as its journey state, with why it is there,
  what comes next and who does it. Two cases need the move that brought it
  there:
  - a failure, said of its analysis or of its actions;
  - a completion, said answered or verified.
- Analysing is said only while an analysis of this attempt runs. Queued, it
  is ready. Queued or running too long, it is said late, and it can be
  asked for again.
- Stopped by a person, it is ready, never failed.
- A question answered in part is said partial; a decision on a partial
  analysis says so.
- The five steps follow the state, never a screen. A cancelled one stays
  where it was withdrawn; a question ends at its results.
- What a person may do is the lifecycle's: no control a route would refuse.
  Archived, only restored.
- The matrix covers every lifecycle state and every move, and each state's
  controls are within its row.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from leka.intentions import MATRIX, TRANSITIONS, IntentionStatus, JourneyState, journey
from leka.intentions.journey import (
    ANALYSIS_DEADLINE,
    QUEUE_PATIENCE,
    AnalysisSeen,
    Facts,
    LastMove,
    row,
    step_of,
)
from leka.intentions.lifecycle import CANCEL, Actor, move

S = IntentionStatus
J = JourneyState
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _facts(
    status: IntentionStatus,
    *,
    last: str | None = None,
    detail: dict[str, object] | None = None,
    from_status: IntentionStatus | None = None,
    analysis: str | None = None,
    started: timedelta = timedelta(minutes=1),
    changed: timedelta = timedelta(minutes=2),
    acting: bool = True,
    archived: bool = False,
    error: str | None = None,
) -> Facts:
    return Facts(
        status=status,
        version=1,
        changed_at=NOW - changed,
        archived=archived,
        last=(
            LastMove(
                name=last,
                actor="system",
                at=NOW - changed,
                from_status=from_status.value if from_status else None,
                detail=detail or {},
            )
            if last
            else None
        ),
        analysis=(
            AnalysisSeen(
                number=1,
                status=analysis,
                started_at=NOW - started,
                intention_version=1,
                error=error,
            )
            if analysis
            else None
        ),
        acting=acting,
    )


def test_analysing_is_said_only_while_an_analysis_of_this_attempt_runs() -> None:
    running = journey(_facts(S.ANALYSING, last="analysis_started", analysis="running"), NOW)
    assert (running.state, running.next, running.by) == (J.ANALYSING, "wait", "leka")
    assert running.since == NOW - timedelta(minutes=1)
    assert "stop" in running.controls and "cancel" in running.controls
    assert not running.late

    # An analysis from before it was asked again: not this attempt's.
    earlier = _facts(
        S.ANALYSING, last="asked_again", analysis="complete", started=timedelta(minutes=5)
    )
    queued = journey(earlier, NOW)
    assert (queued.state, queued.reason, queued.next) == (J.READY, "queued", "wait")
    # Queued, it may be asked for now: the same job if one is on its way.
    assert "analyse_again" in queued.controls
    assert not queued.late


def test_queued_or_running_too_long_is_said_late_and_can_be_asked_for_again() -> None:
    waited = QUEUE_PATIENCE + timedelta(seconds=1)
    queued = journey(_facts(S.ANALYSING, last="asked_again", changed=waited), NOW)
    assert (queued.state, queued.late) == (J.READY, True)
    assert "analyse_again" in queued.controls

    ran = ANALYSIS_DEADLINE + timedelta(seconds=1)
    stuck = journey(
        _facts(S.ANALYSING, analysis="running", started=ran, changed=ran + timedelta(seconds=1)),
        NOW,
    )
    assert (stuck.state, stuck.late) == (J.ANALYSING, True)
    assert "analyse_again" in stuck.controls


def test_stopped_by_a_person_it_is_ready_never_failed() -> None:
    stopped = journey(_facts(S.SUBMITTED, last="stopped", analysis="stopped"), NOW)
    assert (stopped.state, stopped.reason, stopped.next, stopped.by) == (
        J.READY,
        "stopped",
        "resume",
        "asker",
    )
    assert set(stopped.controls) == {"resume", "ask_again", "cancel"}
    assert stopped.step.at == "analysis"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("interrupted", "interrupted"),
        ("crashed", "crashed"),
        ("TimeoutError", "timed_out"),
        ("no_model", "model"),
        ("RuntimeError", "error"),
    ],
)
def test_an_analysis_failure_says_why_and_keeps_the_error_for_diagnosis(
    error: str, reason: str
) -> None:
    failed = journey(
        _facts(S.FAILED, last="failed", detail={"analysis_id": "a", "error": error}), NOW
    )
    assert (failed.state, failed.reason, failed.technical) == (J.ANALYSIS_FAILED, reason, error)
    assert failed.next == "analyse_again"
    assert {"analyse_again", "ask_again", "cancel"} <= set(failed.controls)
    assert "retry_actions" not in failed.controls


@pytest.mark.parametrize(
    ("detail", "from_status", "reason"),
    [
        ({"plan_id": "p", "error": "http_500", "step": 1}, S.EXECUTING, "step_failed"),
        ({"plan_id": "p", "error": "cancelled", "step": None}, S.EXECUTING, "stopped"),
        ({"plan_id": "p", "failed": ["freeze"]}, S.SCHEDULED, "conditions_changed"),
        (
            {"plan_id": "p", "verification_id": "v", "outcome": "failed"},
            S.VERIFYING,
            "expected_not_met",
        ),
    ],
)
def test_an_action_failure_says_why_and_offers_to_retry_what_failed(
    detail: dict[str, object], from_status: IntentionStatus, reason: str
) -> None:
    failed = journey(_facts(S.FAILED, last="failed", detail=detail, from_status=from_status), NOW)
    assert (failed.state, failed.reason, failed.next, failed.by) == (
        J.ACTION_FAILED,
        reason,
        "retry_actions",
        "approver",
    )
    assert "retry_actions" in failed.controls
    assert failed.step.at == "action"


def test_a_question_answered_whole_or_in_part_an_action_verified() -> None:
    whole = journey(_facts(S.COMPLETED, last="answered", analysis="complete", acting=False), NOW)
    assert (whole.state, whole.next) == (J.RESULT_AVAILABLE, "read_result")
    assert (whole.step.at, whole.step.done, whole.step.last) == ("results", True, 2)
    part = journey(_facts(S.COMPLETED, last="answered", analysis="partial", acting=False), NOW)
    assert (part.state, part.reason) == (J.ANALYSIS_PARTIAL, "partial")
    none = journey(_facts(S.COMPLETED, last="answered", analysis="inconclusive", acting=False), NOW)
    assert (none.state, none.reason) == (J.ANALYSIS_PARTIAL, "inconclusive")
    done = journey(_facts(S.COMPLETED, last="verified", analysis="complete"), NOW)
    assert (done.state, done.next) == (J.DONE, "nothing")
    assert (done.step.at, done.step.done) == ("action", True)


def test_a_decision_on_a_partial_analysis_says_so() -> None:
    whole = journey(_facts(S.AWAITING_DECISION, last="proposed", analysis="complete"), NOW)
    assert (whole.state, whole.reason, whole.by) == (J.DECISION_REQUIRED, None, "approver")
    assert {"decide", "modify_decision"} <= set(whole.controls)
    part = journey(_facts(S.AWAITING_DECISION, last="proposed", analysis="partial"), NOW)
    assert part.reason == "partial"


def test_what_runs_is_said_running_never_done_before_it_is_verified() -> None:
    assert journey(_facts(S.APPROVED, last="approved"), NOW).state == J.APPROVED
    scheduled = journey(_facts(S.SCHEDULED, last="scheduled"), NOW)
    assert (scheduled.state, scheduled.reason, scheduled.next) == (
        J.APPROVED,
        "scheduled",
        "wait_schedule",
    )
    assert "unschedule" in scheduled.controls
    running = journey(_facts(S.EXECUTING, last="execution_started"), NOW)
    assert (running.state, running.controls) == (J.ACTION_RUNNING, ("stop_actions",))
    checked = journey(_facts(S.VERIFYING, last="executed"), NOW)
    assert (checked.state, checked.next) == (J.TO_VERIFY, "wait_verification")
    assert "cancel" not in checked.controls


def test_the_steps_follow_the_state_a_cancelled_one_stays_where_it_was() -> None:
    assert step_of(S.NEEDS_CLARIFICATION, True).at == "intention"
    assert step_of(S.AWAITING_DECISION, True).at == "decision"
    rejected = step_of(S.REJECTED, True)
    assert (rejected.at, rejected.done, rejected.last) == ("decision", True, 3)
    withdrawn = journey(_facts(S.CANCELLED, last="cancelled", from_status=S.AWAITING_DECISION), NOW)
    assert (withdrawn.state, withdrawn.step.at) == (J.CANCELLED, "decision")
    early = journey(_facts(S.CANCELLED, last="cancelled", from_status=S.ANALYSING), NOW)
    assert early.step.at == "analysis"


def test_archived_it_is_only_restored() -> None:
    kept = journey(_facts(S.COMPLETED, last="answered", archived=True, acting=False), NOW)
    assert kept.controls == ("restore",)


def test_clarification_says_whether_its_words_or_its_context_are_in_the_way() -> None:
    unclear = journey(_facts(S.NEEDS_CLARIFICATION, last="clarification_asked"), NOW)
    assert (unclear.state, unclear.reason, unclear.next, unclear.by) == (
        J.NEEDS_CLARIFICATION,
        "unclear",
        "answer",
        "asker",
    )
    blocked = journey(
        _facts(S.NEEDS_CLARIFICATION, last="clarification_asked", detail={"critical": ["x"]}),
        NOW,
    )
    assert blocked.reason == "context_blocked"
    assert {"answer", "ask_again", "cancel"} == set(blocked.controls)


# ── the matrix, held to the lifecycle ───────────────────────────────────────


def test_the_matrix_covers_every_lifecycle_state_and_every_move() -> None:
    stored = {status for r in MATRIX for status in r.stored}
    assert stored == set(IntentionStatus)
    names = {m.name for found in TRANSITIONS.values() for m in found} | {CANCEL.name}
    entered = {name for r in MATRIX for name in r.entered_by}
    assert names <= entered, names - entered
    assert {r.state for r in MATRIX} == set(JourneyState)


def _every_facts() -> list[Facts]:
    found = []
    moves: tuple[tuple[str | None, dict[str, object]], ...] = (
        (None, {}),
        ("failed", {"analysis_id": "a", "error": "crashed"}),
        ("failed", {"plan_id": "p", "error": "x", "step": 1}),
        ("stopped", {}),
        ("verified", {}),
        ("answered", {}),
    )
    for status in IntentionStatus:
        for last, detail in moves:
            for analysis in (None, "running", "partial", "complete"):
                for acting in (True, False):
                    found.append(
                        _facts(status, last=last, detail=detail, analysis=analysis, acting=acting)
                    )
    return found


def test_what_a_person_may_do_is_within_its_row_and_never_what_the_lifecycle_refuses() -> None:
    for facts in _every_facts():
        said = journey(facts, NOW)
        allowed = set(row(said.state).controls) | {"archive", "restore"}
        assert set(said.controls) <= allowed, (facts.status, said.state, said.controls)
        assert facts.status in row(said.state).stored
        if "cancel" in said.controls:
            move(facts.status, S.CANCELLED, Actor.PERSON)
        if "stop" in said.controls:
            move(facts.status, S.SUBMITTED, Actor.PERSON)
        if "ask_again" in said.controls:
            move(facts.status, S.ANALYSING, Actor.PERSON)
