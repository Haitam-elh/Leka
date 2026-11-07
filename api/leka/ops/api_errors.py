"""The API's own errors, kept a little while (LEKA-556): each request that
failed on LEKA's side (a 500), said by its route as declared
(`/api/v1/intentions/{intention_id}`, never its values), its method, the
exception's type, its request id, the organisation when the request said
which, and when.

Held in Redis, the latest KEEP, read and taken out by the incident watch
(leka.admin.incidents): no table to write while the database may be what
failed, and never a wait for the request. A Redis that does not answer only
loses what it would have held — said in the log.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import redis.asyncio as redis
import structlog

from leka.core.config import settings

logger = structlog.get_logger(__name__)

KEY = "leka:ops:api_errors"
KEEP = 1000


def _client() -> redis.Redis:
    return redis.from_url(str(settings.redis_url), socket_connect_timeout=1, socket_timeout=1)


async def record_api_error(
    *,
    method: str,
    route: str,
    exception: str,
    request_id: str | None,
    workspace_id: uuid.UUID | None,
    at: datetime,
) -> None:
    """Kept, the newest first, the oldest past KEEP forgotten. Never raises."""
    said = {
        "method": method[:10],
        "route": route[:200],
        "exception": exception[:100],
        "request_id": (request_id or "")[:64] or None,
        "workspace_id": str(workspace_id) if workspace_id else None,
        "at": at.isoformat(),
    }
    try:
        client = _client()
        try:
            await client.lpush(KEY, json.dumps(said))
            await client.ltrim(KEY, 0, KEEP - 1)
        finally:
            await client.aclose()
    except Exception:
        logger.warning("api_error_not_kept", exc_info=True)


async def drain_api_errors() -> list[dict[str, Any]] | None:
    """Every error kept, the oldest first, taken out at once. None: Redis
    could not be read; they stay for the next reading."""
    try:
        client = _client()
        try:
            async with client.pipeline(transaction=True) as pipe:
                pipe.lrange(KEY, 0, KEEP - 1)
                pipe.delete(KEY)
                kept, _ = await pipe.execute()
        finally:
            await client.aclose()
    except Exception:
        logger.warning("api_errors_unreadable", exc_info=True)
        return None
    found: list[dict[str, Any]] = []
    for raw in reversed(kept or []):
        try:
            said = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except ValueError:
            continue
        if isinstance(said, dict):
            found.append(said)
    return found


__all__ = ["KEY", "drain_api_errors", "record_api_error"]
