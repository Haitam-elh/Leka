"""The state machine of a job run, as data.

LEKA-334. A state machine that is only ever described in a docstring is one nobody can be
sure matches the code, so it is declared once (TRANSITIONS) and asserted here in shape:
every status reachable, no status that can get stuck, the final ones terminal. That the
REPOSITORY only ever moves a run along a declared edge is asserted where the repository
is (tests/test_job_runs.py).

Written before the code, and run to watch it fail.
"""

from __future__ import annotations

from leka.background import (
    FINAL_STATUSES,
    TRANSITIONS,
    JobStatus,
)

# ── The shape of the state machine ────────────────────────────────────────


def test_every_status_declares_where_it_can_go() -> None:
    assert set(TRANSITIONS) == set(JobStatus)


def test_the_final_statuses_are_terminal() -> None:
    """A failed run is failed for good: retrying it makes a NEW run, so the
    history of what happened stays true."""
    assert {JobStatus.SUCCEEDED, JobStatus.FAILED} == FINAL_STATUSES
    for status in FINAL_STATUSES:
        assert TRANSITIONS[status] == frozenset(), f"{status} must have no way out"


def test_every_status_is_reachable_from_queued() -> None:
    reached = {JobStatus.QUEUED}
    frontier = [JobStatus.QUEUED]
    while frontier:
        for successor in TRANSITIONS[frontier.pop()]:
            if successor not in reached:
                reached.add(successor)
                frontier.append(successor)
    assert reached == set(JobStatus), f"declared but unreachable: {set(JobStatus) - reached}"


def test_no_status_can_get_stuck() -> None:
    """Every non-final status has a path to a final one. A run in a state
    nothing can leave is a job that is neither done nor failing, for ever."""
    for start in set(JobStatus) - FINAL_STATUSES:
        reached, frontier = {start}, [start]
        while frontier:
            for successor in TRANSITIONS[frontier.pop()]:
                if successor not in reached:
                    reached.add(successor)
                    frontier.append(successor)
        assert reached & FINAL_STATUSES, f"{start} can never finish"


# ── Claiming: exactly one worker wins ─────────────────────────────────────


# ── Finishing ─────────────────────────────────────────────────────────────


# ── Failing, and trying again ─────────────────────────────────────────────


# ── Recovery: a worker that died ──────────────────────────────────────────


# ── Creating a run ────────────────────────────────────────────────────────


# ── Enqueueing ────────────────────────────────────────────────────────────


# ── The runner ────────────────────────────────────────────────────────────


# ── History: what a customer may see ──────────────────────────────────────
