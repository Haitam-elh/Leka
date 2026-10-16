"""From sign-up to the first answer (LEKA-450), timed from what LEKA keeps.

What these protect: each step's time counted from the step before it, and
the total from sign-up; a step that did not happen said so, the next counted
from the last that did; nothing counted without a sign-up.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from leka.ops.first_answer import steps_of

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_each_step_from_the_one_before_the_total_from_sign_up() -> None:
    steps = steps_of(
        {
            "signed_up": at(0),
            "email_confirmed": at(1),
            "workspace": at(2),
            "source_or_demo": at(4),
            "question": at(5),
            "answer": at(7.5),
        }
    )
    assert [s.took for s in steps] == [0, 60, 60, 120, 60, 150]
    assert steps[-1].total == 450


def test_a_step_that_did_not_happen_is_said_and_the_next_counted_from_the_last() -> None:
    steps = {
        s.name: s
        for s in steps_of(
            {
                "signed_up": at(0),
                "email_confirmed": None,
                "workspace": at(3),
                "source_or_demo": at(5),
                "question": None,
                "answer": None,
            }
        )
    }
    assert (steps["email_confirmed"].at, steps["email_confirmed"].took) == (None, None)
    assert steps["workspace"].took == 180
    assert steps["source_or_demo"].took == 120
    assert steps["answer"].total is None


def test_nothing_is_counted_without_a_sign_up() -> None:
    assert all(s.total is None for s in steps_of({"question": at(5)}))
