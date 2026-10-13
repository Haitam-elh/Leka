"""Where an intention stands, as whoever looks at it reads it (LEKA-443):
one state of its journey, from asked to verified, the same on every screen.
Each state comes with:
- why it is there;
- since when;
- what comes next, and who does it;
- what a person may do now.

The lifecycle (lifecycle.py) says what may follow what, and keeps it. The
journey reads that lifecycle as a person needs it. It looks at:
- the lifecycle's state;
- the move that brought it there (its name, by whom, its detail);
- its latest analysis.

Nothing here is a progress made up for a screen. Each state is what was
kept:

    needs_clarification   not understood enough; what LEKA asks is said
    ready                 understood, nothing being read: queued for an
                          analysis, or stopped by a person
    analysing             an analysis of this attempt is running
    analysis_partial      a question answered in part: a source failed, or
                          nothing conclusive
    analysis_failed       its analysis could not run, or was interrupted
    result_available      a question answered
    decision_required     what it asks to do waits for a person's decision
    approved              decided: its actions to be run, or scheduled
    rejected              decided not to act
    action_running        its actions are running
    action_failed         an action did not succeed, was stopped, or what
                          was expected did not come
    to_verify             what ran, checked against what was expected
    done                  acted on, and verified
    cancelled             withdrawn by a person

Two more states are never an intention's own:
- `draft`: words typed, not asked yet. They live in the composer (this
  browser), and nothing unasked is kept.
- `superseded`: what came of an earlier version of it — an analysis, a
  decision. It is never shown as its result.

MATRIX says, for each state:
- the lifecycle states it is read from;
- the moves that bring it there;
- what a person may do;
- the errors it can say.

docs/intentions.md § 13 is the same table, in words. The tests hold both
to the lifecycle (tests/test_intention_journey.py).

Pure: no database, no clock but the one given.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from leka.intentions.lifecycle import Actor, IntentionStatus, moves

S = IntentionStatus


class JourneyState(enum.StrEnum):
    DRAFT = "draft"
    NEEDS_CLARIFICATION = "needs_clarification"
    READY = "ready"
    ANALYSING = "analysing"
    ANALYSIS_PARTIAL = "analysis_partial"
    ANALYSIS_FAILED = "analysis_failed"
    RESULT_AVAILABLE = "result_available"
    DECISION_REQUIRED = "decision_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTION_RUNNING = "action_running"
    ACTION_FAILED = "action_failed"
    TO_VERIFY = "to_verify"
    DONE = "done"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


J = JourneyState

# Queued this long with no analysis started: said late, and it can be asked
# for again. The analysis sweep runs every 15 minutes.
QUEUE_PATIENCE = timedelta(minutes=5)
# Running this long: no analysis takes it — each capability has its budget
# (15 s), the model its own (60 s). Past this it is said late, and the sweep
# says it interrupted (processing.interrupt_overdue).
ANALYSIS_DEADLINE = timedelta(minutes=10)

# What a person may do, by name: each a route that checks it again.
ANSWER = "answer"  # POST …/answers
ASK_AGAIN = "ask_again"  # POST …/ask
STOP = "stop"  # POST …/stop
RESUME = "resume"  # POST …/analyse, from ready (stopped)
ANALYSE_AGAIN = "analyse_again"  # POST …/analyse
CANCEL = "cancel"  # POST …/cancel
DECIDE = "decide"  # POST /decisions/{id}/votes
MODIFY_DECISION = "modify_decision"  # a vote `modify`, while it is open
START_ACTIONS = "start_actions"  # POST …/plans, …/plans/{id}/start
UNSCHEDULE = "unschedule"  # POST …/plans/{id}/cancel, before it runs
STOP_ACTIONS = "stop_actions"  # POST …/plans/{id}/cancel, while it runs
RETRY_ACTIONS = "retry_actions"  # POST …/plans, after a failure
REPORT_OUTCOME = "report_outcome"  # POST …/verifications/{id}/report
ARCHIVE = "archive"
RESTORE = "restore"

CONTROLS = (
    ANSWER,
    ASK_AGAIN,
    STOP,
    RESUME,
    ANALYSE_AGAIN,
    CANCEL,
    DECIDE,
    MODIFY_DECISION,
    START_ACTIONS,
    UNSCHEDULE,
    STOP_ACTIONS,
    RETRY_ACTIONS,
    REPORT_OUTCOME,
    ARCHIVE,
    RESTORE,
)

# Who moves it on from here.
ASKER, APPROVER, LEKA = "asker", "approver", "leka"


# ── what it is read from ────────────────────────────────────────────────────


@dataclass(frozen=True)
class LastMove:
    """The move that brought it to its state, as its history keeps it."""

    name: str
    actor: str
    at: datetime
    from_status: str | None = None
    reason: str | None = None
    detail: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisSeen:
    """Its latest analysis, briefly."""

    number: int
    status: str
    started_at: datetime
    intention_version: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class Facts:
    status: IntentionStatus
    version: int
    changed_at: datetime
    archived: bool = False
    last: LastMove | None = None
    analysis: AnalysisSeen | None = None
    # Whether it asks for something to be done on systems: a decision, then
    # actions. A question answered stops at its results.
    acting: bool = True


# ── what it says ────────────────────────────────────────────────────────────

STEPS = ("intention", "analysis", "results", "decision", "action")


@dataclass(frozen=True)
class Step:
    """Where the five steps put it: the step it is at, the last it reached
    (what may be opened), whether that step is itself done, and the last it
    goes through — a question ends at its results."""

    at: str
    reached: int
    done: bool = False
    last: int = 4


@dataclass(frozen=True)
class Journey:
    state: JourneyState
    since: datetime
    # Why it is there, as a code the screens say in words: queued, stopped,
    # interrupted, partial, step_failed…
    reason: str | None
    # What comes next, and who: answer, wait, resume, decide…
    next: str
    by: str | None
    controls: tuple[str, ...]
    step: Step
    # Past what it should take: queued too long, or running too long.
    late: bool = False
    # The error as kept — its type — for whoever diagnoses it; never the
    # words a person reads.
    technical: str | None = None


def _analysis_reason(error: str | None) -> str:
    """Why an analysis did not run, as a person can act on it."""
    if error is not None and error in ("interrupted", "crashed"):
        return error
    if error in ("TimeoutError", "timed_out"):
        return "timed_out"
    if error in ("no_model", "model_failed", "ungrounded"):
        return "model"
    if error == "context_blocked":
        return "context_blocked"
    return "error"


def _action_reason(last: LastMove) -> str:
    """Why its actions failed: stopped by a person while they ran; what was
    expected did not come (its verification); what had to hold at its time no
    longer did (a scheduled plan's checks); else a step did not succeed."""
    detail = last.detail
    if detail.get("error") == "cancelled":
        return "stopped"
    if "verification_id" in detail:
        return "expected_not_met"
    if "failed" in detail:
        return "conditions_changed"
    return "step_failed"


def _from_actions(last: LastMove | None) -> bool:
    """Whether its failure came from its actions or their outcome — the
    analysis's carries its analysis's id."""
    if last is None:
        return False
    detail = last.detail
    return "analysis_id" not in detail and (
        "plan_id" in detail or "verification_id" in detail or last.from_status == S.VERIFYING
    )


def step_of(status: IntentionStatus, acting: bool, last: LastMove | None = None) -> Step:
    """The five steps, as the lifecycle puts it — a cancelled one where it
    was when withdrawn."""
    ends = 4 if acting else 2
    if status == S.CANCELLED:
        was = S(last.from_status) if last is not None and last.from_status else S.SUBMITTED
        if was == S.CANCELLED:
            was = S.SUBMITTED
        return step_of(was, acting)
    if status == S.NEEDS_CLARIFICATION:
        return Step("intention", 0, last=ends)
    if status in (S.SUBMITTED, S.ANALYSING):
        return Step("analysis", 1, last=ends)
    if status == S.FAILED:
        if _from_actions(last):
            return Step("action", 4, last=4)
        return Step("analysis", 1, last=ends)
    if status == S.AWAITING_DECISION:
        return Step("decision", 3, last=4)
    if status == S.REJECTED:
        return Step("decision", 3, done=True, last=3)
    if status in (S.APPROVED, S.SCHEDULED, S.EXECUTING, S.VERIFYING):
        return Step("action", 4, last=4)
    # Completed: acted on and verified, or a question answered.
    if acting:
        return Step("action", 4, done=True, last=4)
    return Step("results", 2, done=True, last=2)


def _lifecycle_controls(status: IntentionStatus) -> set[str]:
    """What the lifecycle lets a person do from this state — the same rule
    the routes apply."""
    allowed: set[str] = set()
    for each in moves(status):
        if Actor.PERSON not in each.by:
            continue
        if each.to == S.CANCELLED:
            allowed.add(CANCEL)
        elif each.to == S.SUBMITTED:
            allowed.add(STOP)
        elif each.to == S.ANALYSING and status != S.SUBMITTED:
            allowed.add(ASK_AGAIN)
    if status == S.NEEDS_CLARIFICATION:
        allowed.add(ANSWER)
    if status == S.SUBMITTED:
        allowed |= {RESUME, ASK_AGAIN}
    return allowed


def journey(facts: Facts, now: datetime) -> Journey:
    """Its state, why, since when, what next and by whom, what may be done."""
    status, last = facts.status, facts.last
    since = facts.changed_at
    step = step_of(status, facts.acting, last)
    allowed = _lifecycle_controls(status)

    def said(
        state: JourneyState,
        reason: str | None,
        next_: str,
        by: str | None,
        controls: set[str],
        *,
        late: bool = False,
        technical: str | None = None,
        at: datetime | None = None,
    ) -> Journey:
        kept = (allowed | controls) if not facts.archived else {RESTORE}
        return Journey(
            state=state,
            since=at or since,
            reason=reason,
            next=next_,
            by=by,
            controls=tuple(c for c in CONTROLS if c in kept),
            step=step,
            late=late,
            technical=technical,
        )

    analysis = facts.analysis
    if status == S.CANCELLED:
        return said(J.CANCELLED, "by_person", "nothing", None, {ARCHIVE})
    if status == S.NEEDS_CLARIFICATION:
        blocked = last is not None and "critical" in last.detail
        return said(
            J.NEEDS_CLARIFICATION,
            "context_blocked" if blocked else "unclear",
            "answer",
            ASKER,
            set(),
        )
    if status == S.SUBMITTED:
        stopped = last is not None and last.name == "stopped"
        return said(J.READY, "stopped" if stopped else "queued", "resume", ASKER, set())
    if status == S.ANALYSING:
        running = (
            analysis is not None and analysis.status == "running" and analysis.started_at >= since
        )
        if running and analysis is not None:
            late = now - analysis.started_at > ANALYSIS_DEADLINE
            return said(
                J.ANALYSING,
                None,
                "wait",
                LEKA,
                {ANALYSE_AGAIN} if late else set(),
                late=late,
                at=analysis.started_at,
            )
        late = now - since > QUEUE_PATIENCE
        return said(J.READY, "queued", "wait", LEKA, {ANALYSE_AGAIN} if late else set(), late=late)
    if status == S.FAILED:
        if last is not None and _from_actions(last):
            return said(
                J.ACTION_FAILED,
                _action_reason(last),
                "retry_actions",
                APPROVER,
                {RETRY_ACTIONS},
                technical=str(last.detail.get("error") or "") or None,
            )
        error = None
        if last is not None:
            error = str(last.detail.get("error") or "") or None
        if error is None and analysis is not None:
            error = analysis.error
        return said(
            J.ANALYSIS_FAILED,
            _analysis_reason(error),
            "analyse_again",
            ASKER,
            {ANALYSE_AGAIN},
            technical=error,
        )
    if status == S.AWAITING_DECISION:
        partial = analysis is not None and analysis.status in ("partial", "inconclusive")
        return said(
            J.DECISION_REQUIRED,
            "partial" if partial else None,
            "decide",
            APPROVER,
            {DECIDE, MODIFY_DECISION},
        )
    if status == S.APPROVED:
        return said(J.APPROVED, None, "start_actions", APPROVER, {START_ACTIONS})
    if status == S.SCHEDULED:
        return said(J.APPROVED, "scheduled", "wait_schedule", LEKA, {UNSCHEDULE})
    if status == S.REJECTED:
        return said(J.REJECTED, "by_person", "ask_again", ASKER, {ARCHIVE})
    if status == S.EXECUTING:
        return said(J.ACTION_RUNNING, None, "follow_actions", LEKA, {STOP_ACTIONS})
    if status == S.VERIFYING:
        return said(J.TO_VERIFY, None, "wait_verification", LEKA, {REPORT_OUTCOME})
    # Completed.
    if last is not None and last.name == "verified":
        return said(J.DONE, None, "nothing", None, {ARCHIVE})
    if analysis is not None and analysis.status in ("partial", "inconclusive"):
        return said(J.ANALYSIS_PARTIAL, analysis.status, "read_result", ASKER, {ARCHIVE})
    return said(J.RESULT_AVAILABLE, None, "read_result", ASKER, {ARCHIVE})


# ── the matrix ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Row:
    """One state of the journey: what it is read from, how it is reached,
    what a person may do there, the errors it says."""

    state: JourneyState
    stored: tuple[IntentionStatus, ...]
    entered_by: tuple[str, ...]
    controls: tuple[str, ...]
    reasons: tuple[str, ...] = ()


MATRIX: tuple[Row, ...] = (
    Row(J.DRAFT, (), (), ()),
    Row(
        J.NEEDS_CLARIFICATION,
        (S.NEEDS_CLARIFICATION,),
        ("clarification_asked",),
        (ANSWER, ASK_AGAIN, CANCEL),
        ("unclear", "context_blocked"),
    ),
    Row(
        J.READY,
        (S.SUBMITTED, S.ANALYSING),
        ("stopped", "asked_again", "clarified", "retried", "resumed"),
        (RESUME, ASK_AGAIN, ANALYSE_AGAIN, STOP, CANCEL),
        ("queued", "stopped"),
    ),
    Row(
        J.ANALYSING,
        (S.ANALYSING,),
        ("analysis_started", "asked_again", "clarified", "retried", "resumed"),
        (STOP, ASK_AGAIN, ANALYSE_AGAIN, CANCEL),
    ),
    Row(
        J.ANALYSIS_PARTIAL,
        (S.COMPLETED,),
        ("answered",),
        (ASK_AGAIN, ARCHIVE),
        ("partial", "inconclusive"),
    ),
    Row(
        J.ANALYSIS_FAILED,
        (S.FAILED,),
        ("failed",),
        (ANALYSE_AGAIN, ASK_AGAIN, CANCEL),
        ("interrupted", "crashed", "timed_out", "model", "context_blocked", "error"),
    ),
    Row(J.RESULT_AVAILABLE, (S.COMPLETED,), ("answered",), (ASK_AGAIN, ARCHIVE)),
    Row(
        J.DECISION_REQUIRED,
        (S.AWAITING_DECISION,),
        ("proposed",),
        (DECIDE, MODIFY_DECISION, ASK_AGAIN, CANCEL),
        ("partial",),
    ),
    Row(
        J.APPROVED,
        (S.APPROVED, S.SCHEDULED),
        ("approved", "scheduled", "unscheduled"),
        (START_ACTIONS, UNSCHEDULE, CANCEL),
        ("scheduled",),
    ),
    Row(J.REJECTED, (S.REJECTED,), ("rejected",), (ASK_AGAIN, ARCHIVE), ("by_person",)),
    Row(J.ACTION_RUNNING, (S.EXECUTING,), ("execution_started",), (STOP_ACTIONS,)),
    Row(
        J.ACTION_FAILED,
        (S.FAILED,),
        ("failed",),
        (RETRY_ACTIONS, ASK_AGAIN, CANCEL),
        ("step_failed", "stopped", "conditions_changed", "expected_not_met"),
    ),
    Row(J.TO_VERIFY, (S.VERIFYING,), ("executed",), (REPORT_OUTCOME,)),
    Row(J.DONE, (S.COMPLETED,), ("verified",), (ASK_AGAIN, ARCHIVE)),
    Row(J.CANCELLED, (S.CANCELLED,), ("cancelled",), (ARCHIVE,), ("by_person",)),
    Row(J.SUPERSEDED, (), ("asked_again", "clarified"), ()),
)


def row(state: JourneyState) -> Row:
    return next(r for r in MATRIX if r.state == state)
