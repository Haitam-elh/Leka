"""Publishing an event.

The one function other modules call. It writes into the CALLER'S session, which
is the whole point: since LEKA-330 a request is one transaction, so the event
commits with the change that caused it and rolls back with it. There is no
second commit here and there must not be one — an event that outlives a rolled
back change is a job running for something that never happened.
"""

from __future__ import annotations

import json
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from leka.background.models import Event
from leka.background.repository import EventRepository
from leka.core.request_context import current_request_id

# dotted lowercase words: "source.sync_requested". One shape, so a type can be
# searched for and routed without anyone wondering about case or spaces.
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_MAX_TYPE_LENGTH = 100

# An event says WHAT happened and to WHICH thing. Raw material belongs in the
# object store (ADR 010); this limit is what keeps an outbox row from becoming
# a second place to put it.
MAX_PAYLOAD_BYTES = 16_384


async def publish_event(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    event_type: str,
    payload: dict[str, object] | None = None,
    *,
    dedupe_key: str | None = None,
) -> Event | None:
    """Record that something happened in a workspace.

    `workspace_id` is the caller's own — from its principal, never from a
    request body. Returns the event, or None if `dedupe_key` was already
    published for this workspace: a webhook delivered twice is one event.

    Raises ValueError for a type or a payload this module will not carry, so a
    bad event fails where it is written rather than in the dispatcher.
    """
    if len(event_type) > _MAX_TYPE_LENGTH or not _EVENT_TYPE.match(event_type):
        msg = (
            f"invalid event type {event_type!r}: dotted lowercase words of at most "
            f"{_MAX_TYPE_LENGTH} characters, like 'source.sync_requested'"
        )
        raise ValueError(msg)

    body = payload or {}
    try:
        size = len(json.dumps(body, separators=(",", ":")).encode())
    except (TypeError, ValueError) as error:
        msg = f"event payload must be JSON: {error}"
        raise ValueError(msg) from error
    if size > MAX_PAYLOAD_BYTES:
        msg = (
            f"event payload is {size} bytes, over the {MAX_PAYLOAD_BYTES} limit. "
            "An event names what happened; the data goes to the object store."
        )
        raise ValueError(msg)

    return await EventRepository(session, workspace_id).insert_once(
        event_type=event_type,
        payload=body,
        dedupe_key=dedupe_key,
        request_id=current_request_id(),
    )
