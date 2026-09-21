"""Rate limiting on Redis.

Deliberately NOT account lockout. Locking an account after N failed attempts
means anyone who knows an email address can deny that person access —
a denial-of-service dressed as a security control. Rate limiting slows an
attacker without handing them a weapon.

Reusable by any module; identity is simply the first to need it.
"""

from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as redis
import structlog

from leka.core.config import settings

logger = structlog.get_logger(__name__)

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    """One client for the process, created on first use."""
    global _client
    if _client is None:
        _client = redis.from_url(
            str(settings.redis_url), socket_connect_timeout=2, socket_timeout=2
        )
    return _client


@dataclass(frozen=True)
class Limit:
    """How many of something, over how long."""

    attempts: int
    window_seconds: int

    def key(self, scope: str, identifier: str) -> str:
        return f"leka:ratelimit:{scope}:{identifier}"


@dataclass(frozen=True)
class LimitVerdict:
    allowed: bool
    remaining: int
    retry_after_seconds: int


# The limits this platform enforces. Gathered here rather than scattered
# through routes, so that "what do we actually throttle?" has one answer.
#
# Per IP and per account, because they defend against different things: per
# IP stops one machine trying many accounts, per account stops many machines
# trying one.
LOGIN_PER_IP = Limit(attempts=5, window_seconds=60)
LOGIN_PER_ACCOUNT = Limit(attempts=10, window_seconds=3600)
REGISTER_PER_IP = Limit(attempts=3, window_seconds=3600)
PASSWORD_RESET_PER_IP = Limit(attempts=3, window_seconds=3600)
PASSWORD_RESET_PER_EMAIL = Limit(attempts=3, window_seconds=3600)
VERIFICATION_RESEND_PER_ACCOUNT = Limit(attempts=3, window_seconds=3600)


async def consume(scope: str, identifier: str, limit: Limit) -> LimitVerdict:
    """Count one attempt and say whether it is allowed.

    A fixed window: INCR, and set the expiry on the first increment. Simpler
    than a sliding window and adequate here — the worst case is twice the
    allowance across a window boundary, which matters for a billing quota and
    not for slowing down a password guesser.

    The counter and its expiry go out in ONE atomic round trip. They used to
    be separate calls, and a Redis restart or a dropped connection between
    the two left a counter with no expiry at all — a key that never decays,
    and a person locked out for good with nothing in the logs to say why. The
    symptom would reach us as "I can't sign in any more", which is the worst
    kind of bug to receive.

    A transactional pipeline rather than a Lua script: MULTI/EXEC is enough
    to make the three commands indivisible, and it needs no script to keep,
    load or version. EXPIRE ... NX sets the window only when the key has none
    — the same thing the old `if used == 1` meant, and it also repairs a key
    that somehow lost its expiry instead of leaving it stuck forever.

    Fails OPEN if Redis is unreachable, and says so loudly. The alternative
    is that a Redis hiccup locks every customer out of their account, which
    is a worse outcome than a few minutes of unthrottled attempts.
    """
    key = limit.key(scope, identifier)
    try:
        async with _redis().pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.expire(key, limit.window_seconds, nx=True)
            pipeline.ttl(key)
            used, _, ttl = await pipeline.execute()
    except Exception as error:
        logger.error("rate_limit_unavailable", scope=scope, error=str(error))
        return LimitVerdict(allowed=True, remaining=limit.attempts, retry_after_seconds=0)

    remaining = max(0, limit.attempts - int(used))
    allowed = int(used) <= limit.attempts
    if not allowed:
        logger.info("rate_limited", scope=scope)
    return LimitVerdict(
        allowed=allowed,
        remaining=remaining,
        retry_after_seconds=max(int(ttl), 0),
    )


async def reset(scope: str, identifier: str, limit: Limit) -> None:
    """Forget the attempts counted so far.

    Called after a successful sign-in: someone who got in should not be
    throttled by the typos they made on the way.
    """
    try:
        await _redis().delete(limit.key(scope, identifier))
    except Exception as error:  # pragma: no cover - same fail-open reasoning
        logger.warning("rate_limit_reset_failed", scope=scope, error=str(error))
