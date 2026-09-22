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


not_a_function = "this is a string, not a callable"
