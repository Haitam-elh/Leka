"""An intention's lifecycle (LEKA-384): where a request stands, from the
moment someone asks to the moment what was done is verified — and what may
move it, and who.

    submitted ──▶ analysing ──▶ awaiting_decision ──▶ approved ──▶ executing
                    │                │                 │   ▲         │
                    │                ├──▶ rejected     ▼   │         ▼
                    │                │             scheduled     verifying ──▶ completed
                    └──▶ completed   └──▶ analysing                  │
                         (answered)       (asked again)    failed ◀──┘ (and from executing)

    submitted, analysing ──▶ needs_clarification ──▶ analysing   (LEKA-385:
                             not understood enough; clarified by asking again)
    analysing ──▶ submitted ──▶ analysing   (LEKA-443: its analysis stopped by
                  a person — kept, ready to analyse — and resumed)
    any state not closed ──▶ cancelled     (the asker withdraws it)
    failed ──▶ analysing | executing        (tried again)
    completed | rejected ──▶ analysing      (asked again)

Each state is said by who moves an intention there: LEKA itself (`system`
— the context assembled, the analysis done, an action run) or a person
(`person` — approving, rejecting, cancelling, asking again). An approval
is a person's, never the system's: the reason this module exists
(docs/architecture.md § 5). Who among people may — the asker, an approver
— is the routes' permission (LEKA-390 decides); here, only that a person
must.

Pure: what may follow what, said once, tested in a millisecond
(tests/test_intention_lifecycle.py). The service records each move as an
event of the intention's history, never rewritten.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass


class IntentionStatus(enum.StrEnum):
    # Asked: its words and scope kept, nothing being read — before its
    # analysis starts, or once a person stopped it (LEKA-443): ready to
    # analyse.
    SUBMITTED = "submitted"
    # Not understood enough to go on (LEKA-385): what LEKA would ask is
    # said; asked again, it is read again.
    NEEDS_CLARIFICATION = "needs_clarification"
    # Its context assembled, LEKA analysing it (LEKA-387, 388).
    ANALYSING = "analysing"
    # Findings and recommendations ready: a person decides (LEKA-389, 390).
    AWAITING_DECISION = "awaiting_decision"
    # A person said act (LEKA-390).
    APPROVED = "approved"
    # To be acted on at a time chosen (LEKA-391).
    SCHEDULED = "scheduled"
    # Its actions running (LEKA-391).
    EXECUTING = "executing"
    # What was done, checked (LEKA-392).
    VERIFYING = "verifying"
    # Answered, or acted on and verified.
    COMPLETED = "completed"
    # A person said not to act.
    REJECTED = "rejected"
    # Its analysis or its actions failed: to be tried again, or cancelled.
    FAILED = "failed"
    # Withdrawn by a person.
    CANCELLED = "cancelled"


class Actor(enum.StrEnum):
    PERSON = "person"
    SYSTEM = "system"


S = IntentionStatus
P, SYS = Actor.PERSON, Actor.SYSTEM


@dataclass(frozen=True)
class Move:
    """A transition: to where, by whom, under what name in the history."""

    to: IntentionStatus
    by: frozenset[Actor]
    name: str


def _move(to: IntentionStatus, name: str, *by: Actor) -> Move:
    return Move(to=to, by=frozenset(by), name=name)


# What may follow each state — and nothing else.
TRANSITIONS: Mapping[IntentionStatus, tuple[Move, ...]] = {
    S.SUBMITTED: (
        _move(S.ANALYSING, "analysis_started", SYS),
        _move(S.NEEDS_CLARIFICATION, "clarification_asked", SYS),
        _move(S.FAILED, "failed", SYS),
        # Stopped, then resumed by a person (LEKA-443).
        _move(S.ANALYSING, "resumed", P),
    ),
    S.NEEDS_CLARIFICATION: (_move(S.ANALYSING, "clarified", P),),
    S.ANALYSING: (
        _move(S.AWAITING_DECISION, "proposed", SYS),
        # Asked again, and still not understood enough.
        _move(S.NEEDS_CLARIFICATION, "clarification_asked", SYS),
        _move(S.COMPLETED, "answered", SYS),
        _move(S.FAILED, "failed", SYS),
        # Asked again while being analysed: analysed again.
        _move(S.ANALYSING, "asked_again", P),
        # Its analysis stopped by a person: kept, ready to analyse (LEKA-443).
        _move(S.SUBMITTED, "stopped", P),
    ),
    S.AWAITING_DECISION: (
        _move(S.APPROVED, "approved", P),
        _move(S.REJECTED, "rejected", P),
        _move(S.ANALYSING, "asked_again", P),
    ),
    S.APPROVED: (
        _move(S.SCHEDULED, "scheduled", P, SYS),
        _move(S.EXECUTING, "execution_started", P, SYS),
    ),
    S.SCHEDULED: (
        _move(S.EXECUTING, "execution_started", P, SYS),
        _move(S.APPROVED, "unscheduled", P),
    ),
    S.EXECUTING: (
        _move(S.VERIFYING, "executed", SYS),
        _move(S.FAILED, "failed", SYS),
    ),
    S.VERIFYING: (
        _move(S.COMPLETED, "verified", SYS, P),
        _move(S.FAILED, "failed", SYS, P),
    ),
    S.COMPLETED: (_move(S.ANALYSING, "asked_again", P),),
    S.REJECTED: (_move(S.ANALYSING, "asked_again", P),),
    S.FAILED: (
        _move(S.ANALYSING, "retried", P, SYS),
        _move(S.EXECUTING, "retried", P, SYS),
    ),
    S.CANCELLED: (),
}

# Done with: no move but asking again. Cancelled is final.
CLOSED = frozenset({S.COMPLETED, S.REJECTED, S.CANCELLED})
# Running: nothing to cancel once actions are under way — they finish, or
# fail, and are verified (LEKA-391 stops one, not this).
UNCANCELLABLE = frozenset({S.EXECUTING, S.VERIFYING}) | CLOSED
CANCEL = _move(S.CANCELLED, "cancelled", P)

# How the list groups them (mockup 07): in progress, scheduled, finished.
PHASES: Mapping[str, frozenset[IntentionStatus]] = {
    "active": frozenset(
        {
            S.SUBMITTED,
            S.NEEDS_CLARIFICATION,
            S.ANALYSING,
            S.AWAITING_DECISION,
            S.APPROVED,
            S.EXECUTING,
            S.VERIFYING,
            S.FAILED,
        }
    ),
    "scheduled": frozenset({S.SCHEDULED}),
    "finished": frozenset({S.COMPLETED, S.REJECTED, S.CANCELLED}),
}


class IllegalTransitionError(ValueError):
    """A move the lifecycle does not allow, or not by this actor."""

    def __init__(self, at: IntentionStatus, to: IntentionStatus, by: Actor) -> None:
        super().__init__(f"An intention {at.value} cannot become {to.value} by a {by.value}.")
        self.at, self.to, self.by = at, to, by


def moves(at: IntentionStatus) -> tuple[Move, ...]:
    """What may follow a state: its transitions, and cancelling when it can
    be cancelled."""
    found = TRANSITIONS[at]
    return found if at in UNCANCELLABLE else (*found, CANCEL)


def move(at: IntentionStatus, to: IntentionStatus, by: Actor) -> Move:
    """The move from `at` to `to` by `by` — or IllegalTransitionError."""
    for candidate in moves(at):
        if candidate.to is to and by in candidate.by:
            return candidate
    raise IllegalTransitionError(at, to, by)


def phase(status: IntentionStatus) -> str:
    return next(name for name, states in PHASES.items() if status in states)
