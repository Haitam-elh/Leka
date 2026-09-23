"""Jobs for the background tests to run.

Named by dotted path, like every real job: `tests.background_jobs.succeed`. They
live in a module of their own because the runner resolves a job by importing it,
which is exactly the path under test.
"""

from __future__ import annotations

import time
from typing import Any

from leka.core.request_context import current_request_id

CALLS: list[tuple[str, Any]] = []


def reset() -> None:
    CALLS.clear()


def succeed(*args: Any, **kwargs: Any) -> str:
    CALLS.append(("succeed", (args, kwargs)))
    return "ok"


def fail(*args: Any) -> None:
    CALLS.append(("fail", args))
    msg = "boom: the job failed"
    raise RuntimeError(msg)


def observe_request_id() -> None:
    CALLS.append(("request_id", current_request_id()))


def sleep(seconds: float) -> None:
    CALLS.append(("sleep", seconds))
    time.sleep(seconds)


def record_event(event_id: str) -> None:
    """What an event route's job looks like: one argument, the event id."""
    CALLS.append(("record_event", (event_id, current_request_id())))


def flaky(name: str, fail_times: int) -> None:
    """Fails the first `fail_times` times it is called, then works."""
    seen = sum(1 for call, payload in CALLS if call == "flaky" and payload == name)
    CALLS.append(("flaky", name))
    if seen < fail_times:
        msg = f"flaky job {name!r} failing on call {seen + 1}"
        raise RuntimeError(msg)


def label(text: str) -> None:
    CALLS.append(("label", text))


not_a_function = "this is a string, not a callable"


def leak(value: str) -> None:
    """Fails with an argument in its message, the way a connection error
    quotes the URL it could not reach — password included."""
    CALLS.append(("leak", value))
    msg = f"could not connect with {value}"
    raise RuntimeError(msg)
