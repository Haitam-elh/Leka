"""Backing-service probes behind /api/v1/health.

A health endpoint that returns 200 because the process is running tells you
nothing: the interesting failure is an API that is up while PostgreSQL is
unreachable. These probes issue a real query and a real PING.

Every probe is bounded in time. An unreachable host does not always refuse a
connection — it can simply never answer, and an unbounded probe turns a
health check into a hung request that a load balancer reads as a timeout
instead of as "this dependency is down".

The Redis client lives here for now. When leka.platform grows its queue, the
client moves there and this module calls it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import redis.asyncio as redis
import structlog

from leka.core.config import settings
from leka.db import check_database

logger = structlog.get_logger(__name__)

PROBE_TIMEOUT_SECONDS = 3.0


async def _check_redis() -> bool:
    client = redis.from_url(
        str(settings.redis_url),
        socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
        socket_timeout=PROBE_TIMEOUT_SECONDS,
    )
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


async def check_backing_services() -> dict[str, bool]:
    """Probe every service the API cannot work without.

    Never raises and never hangs: a probe that crashes turns a degraded
    report into a 500, and a probe that blocks hides which dependency is
    actually down.
    """
    probes: dict[str, Callable[[], Awaitable[bool]]] = {
        "database": check_database,
        "redis": _check_redis,
    }
    report: dict[str, bool] = {}
    for name, probe in probes.items():
        try:
            report[name] = await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("health_probe_timeout", service=name)
            report[name] = False
        except Exception as exc:
            logger.warning("health_probe_failed", service=name, error=str(exc))
            report[name] = False
    return report
