"""Circuit breakers (LEKA-408): a dependency that keeps failing is left alone
for a while — its callers go elsewhere, or say plainly it is down — instead of
every request waiting on it in turn.

    allow(name)     may it be called now: closed, or half-open (one try)
    failure(name)   it failed as a dependency fails — down, slow, overloaded
    success(name)   it answered: closed again
    state(name)     closed · open · half_open, for the metrics
    known()         every breaker that has tripped, for the metrics

One breaker per dependency, shared by every process through Redis: the API
and the workers see the same state, so a provider down for one is down for
all. `failure()` counts within WINDOW; at THRESHOLD the breaker opens for
COOLDOWN; after it, the next call goes through (half-open) — answered, it
closes; failed, it opens again at once.

It never stands in the way by itself: Redis unreachable, every call is
allowed and the failure logged. A breaker that blocks because its own store
is down would be the outage it exists to contain.

Only failures of the DEPENDENCY count — a timeout, a 5xx, a refused
connection — never a 4xx the caller caused: a bad request says nothing about
whether the other side is up.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

import redis.asyncio as redis
import structlog

from leka.core.config import settings

logger = structlog.get_logger(__name__)

PREFIX = "leka:breaker:"
KNOWN = f"{PREFIX}known"

State = Literal["closed", "open", "half_open"]


@dataclass(frozen=True)
class Policy:
    """When it opens, and for how long."""

    threshold: int = 5
    window_seconds: int = 60
    cooldown_seconds: int = 30


DEFAULT = Policy()

_clients: dict[int, redis.Redis] = {}


def _redis() -> redis.Redis:
    """One client per event loop: a job runs in its own (asyncio.run), and a
    client bound to a finished loop cannot be used again."""
    loop = id(asyncio.get_running_loop())
    client = _clients.get(loop)
    if client is None:
        if len(_clients) > 32:
            # Loops long finished (one per job, per test): let them go.
            _clients.clear()
        client = redis.from_url(str(settings.redis_url), socket_connect_timeout=1, socket_timeout=1)
        _clients[loop] = client
    return client


def _keys(name: str) -> tuple[str, str, str]:
    return f"{PREFIX}{name}:fails", f"{PREFIX}{name}:open", f"{PREFIX}{name}:half"


async def allow(name: str) -> bool:
    """Closed or half-open: yes. Open: no — go elsewhere, or say it is down."""
    _, opened, _ = _keys(name)
    try:
        return not await _redis().exists(opened)
    except Exception:
        logger.warning("breaker_unavailable", breaker=name, exc_info=True)
        return True


async def failure(name: str, policy: Policy = DEFAULT) -> bool:
    """Counted; True when this failure opened it."""
    fails, opened, half = _keys(name)
    try:
        client = _redis()
        if await client.exists(half) and not await client.exists(opened):
            # Half-open, and the one try failed: open again, at once.
            await _open(client, name, policy)
            return True
        count = await client.incr(fails)
        if count == 1:
            await client.expire(fails, policy.window_seconds)
        if count >= policy.threshold and not await client.exists(opened):
            await _open(client, name, policy)
            return True
    except Exception:
        logger.warning("breaker_unavailable", breaker=name, exc_info=True)
    return False


async def _open(client: redis.Redis, name: str, policy: Policy) -> None:
    fails, opened, half = _keys(name)
    await client.set(opened, "1", ex=policy.cooldown_seconds)
    # Half-open once the cooldown is over, for as long as a window.
    await client.set(half, "1", ex=policy.cooldown_seconds + policy.window_seconds)
    await client.delete(fails)
    await client.sadd(KNOWN, name)
    logger.warning("breaker_opened", breaker=name, cooldown=policy.cooldown_seconds)


async def success(name: str) -> None:
    """It answered: whatever failed before is forgotten."""
    fails, _, half = _keys(name)
    try:
        await _redis().delete(fails, half)
    except Exception:
        logger.warning("breaker_unavailable", breaker=name, exc_info=True)


async def state(name: str) -> State:
    _, opened, half = _keys(name)
    try:
        client = _redis()
        if await client.exists(opened):
            return "open"
        if await client.exists(half):
            return "half_open"
    except Exception:
        logger.warning("breaker_unavailable", breaker=name, exc_info=True)
    return "closed"


async def known() -> list[str]:
    """Every breaker that has opened since Redis last forgot."""
    try:
        members = await _redis().smembers(KNOWN)
    except Exception:
        logger.warning("breaker_unavailable", exc_info=True)
        return []
    return sorted(m.decode() if isinstance(m, bytes) else str(m) for m in members)


class OpenCircuitError(Exception):
    """A dependency left alone for now: its breaker is open."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is failing: not called for a while.")
        self.name = name
