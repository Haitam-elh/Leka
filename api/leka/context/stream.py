"""What happens to a context, as it happens (LEKA-376): server-sent events.

A screen showing a context, a service waiting on one, should not ask again
and again whether LEKA made it again (LEKA-374). It opens a stream:

    retry: 3000                       how long a client waits to reconnect
    event: freshness                  up to date or behind, since when, on how
    data: {"state": …}                many changes, followed or not — at once,
                                      then each time it changes
    id: 2026-10-05T14:02:11+00:00     each time it was made again, after the
    event: check                      cursor: why, by whom, what came of it —
    data: {"trigger": …}              the id is the cursor to resume from
    event: archived | gone | revoked  the end: archived; deleted; the member
                                      removed from the workspace
    event: bye                        the stream's time is up: reconnect with
                                      Last-Event-ID, nothing is missed
    : keep-alive                      every HEARTBEAT seconds of quiet

It reads, every POLL seconds, in a session of its own — a stream holds no
transaction open — and asks every time whether the person is still a
member: removing them ends it at the next look, as it ends the next
request. A stream lasts `timeout` seconds at most; a client reconnects,
and its Last-Event-ID resumes where it was.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from leka.context.repository import ContextRepository
from leka.context.service import ContextService
from leka.db import session_factory, workspace_scope
from leka.platform import MembershipResolver

# How often it looks, how long it may stay quiet, how long a client waits
# before reconnecting, how many checks it tells at a look.
POLL = 2.0
HEARTBEAT = 15.0
RETRY_MS = 3000
MAX_CHECKS = 50


def sse(event: str, data: dict[str, object] | None = None, *, id_: str | None = None) -> str:
    """One server-sent event."""
    lines = [f"id: {id_}"] if id_ else []
    lines += [
        f"event: {event}",
        f"data: {json.dumps(data or {}, separators=(',', ':'), default=str)}",
    ]
    return "\n".join(lines) + "\n\n"


def cursor_of(said: str | None) -> datetime | None:
    """A Last-Event-ID, as the stream gave it: an instant — or nothing."""
    if not said:
        return None
    try:
        return datetime.fromisoformat(said)
    except ValueError:
        return None


async def events(
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    context_id: uuid.UUID,
    after: datetime | None,
    lasting: float,
    poll: float | None = None,
) -> AsyncIterator[str]:
    """What happens to a context, `lasting` seconds at most."""
    yield f"retry: {RETRY_MS}\n\n"
    pause = POLL if poll is None else poll
    clock = asyncio.get_running_loop()
    deadline = clock.time() + lasting
    quiet = clock.time()
    told: dict[str, object] | None = None
    cursor = after
    while True:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                member = await MembershipResolver(session).get_for_user_in_workspace(
                    user_id, workspace_id
                )
                repository = ContextRepository(session, workspace_id)
                context = await repository.context(context_id) if member else None
                checks = (
                    await repository.checks_after(context_id, cursor, limit=MAX_CHECKS)
                    if context
                    else []
                )
                read = ContextService.reads([context])[0] if context else None
                said = ContextService.check_reads(checks)
        if member is None:
            yield sse("revoked")
            return
        if read is None:
            yield sse("gone")
            return
        for check in said:
            cursor = check.checked_at
            yield sse(
                "check",
                check.model_dump(mode="json", exclude={"changes"}),
                id_=cursor.isoformat(),
            )
        fresh = read.freshness.model_dump(mode="json", exclude={"pending"})
        moved = fresh != told
        if moved:
            told = fresh
            yield sse("freshness", {**fresh, "version": read.current_version})
        if read.status == "archived":
            yield sse("archived")
            return
        now = clock.time()
        if now >= deadline:
            yield sse("bye", {"after": cursor.isoformat() if cursor else None})
            return
        if said or moved:
            quiet = now
        elif now - quiet >= HEARTBEAT:
            yield ": keep-alive\n\n"
            quiet = now
        await asyncio.sleep(min(pause, max(0.0, deadline - now)))
