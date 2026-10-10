"""Circuit breakers (LEKA-408): a dependency that keeps failing is left alone
for a while — its callers go elsewhere, or say plainly it is down — instead of
every request waiting on it in turn.

    allow(name)     may it be called now: closed, or half-open (one try, one caller)
    failure(name)   it failed as a dependency fails — down, slow, overloaded
    success(name)   it answered: closed again
    state(name)     closed · open · half_open, for the metrics
    states()        every breaker not closed, and its state — one round trip

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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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


@asynccontextmanager
async def _redis() -> AsyncIterator[redis.Redis]:
    """A client for one operation, closed after it: a job runs in its own
    event loop (asyncio.run), and a client kept across loops ends up bound
    to one already closed."""
    client = redis.from_url(str(settings.redis_url), socket_connect_timeout=1, socket_timeout=1)
    try:
        yield client
    finally:
        await client.aclose()


def _keys(name: str) -> tuple[str, str, str, str]:
    base = f"{PREFIX}{name}"
    return f"{base}:fails", f"{base}:open", f"{base}:half", f"{base}:probe"


async def allow(name: str, policy: Policy = DEFAULT) -> bool:
    """Closed: yes. Open: no — go elsewhere, or say it is down. Half-open:
    yes for ONE caller — the try that tells whether it is back — and no for
    the others until it does."""
    _, opened, half, probe = _keys(name)
    try:
        async with _redis() as client:
            if await client.exists(opened):
                return False
            if await client.exists(half):
                return bool(await client.set(probe, "1", nx=True, ex=policy.window_seconds))
            return True
    except Exception:
        logger.warning("breaker_unavailable", breaker=name, exc_info=True)
        return True


async def failure(name: str, policy: Policy = DEFAULT) -> bool:
    """Counted; True when this failure opened it."""
    fails, opened, half, _ = _keys(name)
    try:
        async with _redis() as client:
            if await client.exists(half) and not await client.exists(opened):
                # Half-open, and the one try failed: open again, at once.
                await _open(client, name, policy)
                return True
            # Counted and given its window together: a counter without a
            # TTL would add up unrelated failures for days.
            async with client.pipeline(transaction=True) as pipeline:
                pipeline.incr(fails)
                pipeline.expire(fails, policy.window_seconds, nx=True)
                count, _ = await pipeline.execute()
            if int(count) >= policy.threshold and not await client.exists(opened):
                await _open(client, name, policy)
                return True
    except Exception:
        logger.warning("breaker_unavailable", breaker=name, exc_info=True)
    return False


async def _open(client: redis.Redis, name: str, policy: Policy) -> None:
    fails, opened, half, probe = _keys(name)
    await client.set(opened, "1", ex=policy.cooldown_seconds)
    # Half-open once the cooldown is over, for as long as a window.
    await client.set(half, "1", ex=policy.cooldown_seconds + policy.window_seconds)
    await client.delete(fails, probe)
    await client.sadd(KNOWN, name)
    logger.warning("breaker_opened", breaker=name, cooldown=policy.cooldown_seconds)


async def success(name: str) -> None:
    """It answered: whatever failed before is forgotten."""
    fails, _, half, probe = _keys(name)
    try:
        async with _redis() as client:
            await client.delete(fails, half, probe)
    except Exception:
        logger.warning("breaker_unavailable", breaker=name, exc_info=True)


async def state(name: str) -> State:
    _, opened, half, _ = _keys(name)
    try:
        async with _redis() as client:
            if await client.exists(opened):
                return "open"
            if await client.exists(half):
                return "half_open"
    except Exception:
        logger.warning("breaker_unavailable", breaker=name, exc_info=True)
    return "closed"


async def states() -> dict[str, State]:
    """Every breaker that has opened and is not closed yet, and its state —
    read in one round trip; those closed again are forgotten from the set."""
    try:
        async with _redis() as client:
            members = sorted(
                m.decode() if isinstance(m, bytes) else str(m) for m in await client.smembers(KNOWN)
            )
            if not members:
                return {}
            keys = [k for name in members for k in _keys(name)[1:3]]
            values = await client.mget(keys)
            found: dict[str, State] = {}
            closed: list[str] = []
            for i, name in enumerate(members):
                opened, half = values[2 * i], values[2 * i + 1]
                if opened:
                    found[name] = "open"
                elif half:
                    found[name] = "half_open"
                else:
                    closed.append(name)
            if closed:
                await client.srem(KNOWN, *closed)
            return found
    except Exception:
        logger.warning("breaker_unavailable", exc_info=True)
        return {}


async def known() -> list[str]:
    """Every breaker that has opened and is not closed again."""
    return sorted(await states())


class OpenCircuitError(Exception):
    """A dependency left alone for now: its breaker is open."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is failing: not called for a while.")
        self.name = name
