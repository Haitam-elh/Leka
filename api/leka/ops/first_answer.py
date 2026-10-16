"""From sign-up to the first answer (LEKA-450): how long a person took, step
by step — read from what LEKA keeps, never from a stopwatch.

    python -m leka.ops.first_answer EMAIL

Each step is the first time it happened for that person:

    signed_up        their account made
    email_confirmed  their address confirmed
    workspace        a workspace of their own joined (the demo's apart)
    source_or_demo   their first source added, or the demo opened — the earlier
    question         their first intention asked
    answer           its analysis delivered — complete or partial

A step that did not happen is said so, and the times after it are counted
from the last one that did. Whether the answer was *useful* is the
observer's call (docs/product/user-test-450.md): this says when it came.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from leka.db import session_factory, system_scope

STEPS = ("signed_up", "email_confirmed", "workspace", "source_or_demo", "question", "answer")


@dataclass(frozen=True)
class Step:
    name: str
    at: datetime | None
    # Seconds since sign-up, and since the step before that happened.
    total: float | None
    took: float | None


def steps_of(times: dict[str, datetime | None]) -> list[Step]:
    """Each step with how long it took — from the last step that happened."""
    start = times.get("signed_up")
    previous = start
    found: list[Step] = []
    for name in STEPS:
        at = times.get(name)
        if at is None or start is None:
            found.append(Step(name, at, None, None))
            continue
        took = (at - previous).total_seconds() if previous is not None else None
        found.append(Step(name, at, (at - start).total_seconds(), took))
        previous = at
    return found


async def times_of(email: str) -> dict[str, datetime | None] | None:
    """When each step first happened for the person with that address —
    None when there is no such person."""
    with system_scope():
        async with session_factory() as session:
            person = (
                await session.execute(
                    text(
                        "SELECT id, created_at, email_verified_at FROM users "
                        "WHERE lower(email) = lower(:email)"
                    ),
                    {"email": email},
                )
            ).first()
            if person is None:
                return None
            user = {"user": person.id}

            async def first(sql: str) -> datetime | None:
                return (await session.execute(text(sql), user)).scalar()

            workspace = await first(
                "SELECT min(m.created_at) FROM memberships m "
                "JOIN workspaces w ON w.id = m.workspace_id "
                "WHERE m.user_id = :user AND NOT w.demo"
            )
            demo = await first(
                "SELECT min(m.created_at) FROM memberships m "
                "JOIN workspaces w ON w.id = m.workspace_id "
                "WHERE m.user_id = :user AND w.demo"
            )
            source = await first("SELECT min(created_at) FROM sources WHERE created_by = :user")
            question = await first(
                "SELECT min(created_at) FROM intentions WHERE created_by = :user"
            )
            answer = await first(
                "SELECT min(a.finished_at) FROM intention_analyses a "
                "JOIN intentions i ON i.id = a.intention_id "
                "WHERE i.created_by = :user AND a.status IN ('complete', 'partial')"
            )
    either = [t for t in (source, demo) if t is not None]
    return {
        "signed_up": person.created_at,
        "email_confirmed": person.email_verified_at,
        "workspace": workspace,
        "source_or_demo": min(either) if either else None,
        "question": question,
        "answer": answer,
    }


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest:02d} s"


def main(argv: Sequence[str] | None = None) -> int:
    given = list(sys.argv[1:] if argv is None else argv)
    if len(given) != 1:
        sys.stderr.write("usage: python -m leka.ops.first_answer EMAIL\n")
        return 2
    times = asyncio.run(times_of(given[0]))
    if times is None:
        sys.stderr.write(f"no one signed up as {given[0]}\n")
        return 1
    sys.stdout.write(f"{'step':<16} {'at (UTC)':<20} {'took':>12} {'since sign-up':>14}\n")
    for step in steps_of(times):
        at = step.at.strftime("%Y-%m-%d %H:%M:%S") if step.at else "did not happen"
        sys.stdout.write(
            f"{step.name:<16} {at:<20} {_clock(step.took):>12} {_clock(step.total):>14}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
