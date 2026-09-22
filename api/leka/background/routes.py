"""Which jobs an event triggers.

A table, in this file, of event type to dotted job paths. Adding a consumer is
one line here.

WHY A TABLE AND NOT A REGISTRY. This module sits below every module that owns a
job (architecture rule 1), so it cannot import them, and a job is named by its
dotted path for the same reason leka.background.jobs explains. A registry that
each module writes itself into would keep that, but the worker would then have
to import every such module before it could dispatch anything — a dependency
on import order that fails only in production. A table has none of that. The
price is that this file names things it does not own; when it has more than a
handful of entries, that is the moment to reconsider.

A route says which job, and which queue it goes on. `high` is work a person is
waiting for; `low` is the sweeps; the default is everything else. It defaults to
the middle, so a route only says so when it has a reason.

A job named here receives ONE argument: the event id, as a string (RQ
serialises to JSON). It reads the event, checks its workspace still exists —
a workspace can be deleted between the event and the job — and does its work.
It must be safe to run twice: dispatch is at-least-once (ADR 013).

AN EVENT WITH NO ENTRY HERE IS MARKED FAILED, not ignored. Dropping it
silently would look exactly like it working.

`tests/test_event_dispatch.py` checks that every path below names a function
that exists. It is empty today because nothing consumes an event yet; the first
connector adds the first line.
"""

from __future__ import annotations

from dataclasses import dataclass

from leka.background.models import JobQueue


@dataclass(frozen=True)
class Route:
    job: str
    queue: JobQueue = JobQueue.DEFAULT


ROUTES: dict[str, tuple[Route, ...]] = {}
