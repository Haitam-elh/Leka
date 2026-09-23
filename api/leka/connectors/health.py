"""Health checks: on demand from the API, and every fifteen minutes from RQ.

One function does the work — `run_health_check` — so a check asked for by an
admin and a check run by the schedule cannot disagree about what healthy
means. Only activated sources are checked on schedule: a draft has nothing
to be healthy for.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog

from leka.connectors.repository import activated_sources
from leka.connectors.service import SourceService
from leka.db import session_factory, system_scope, workspace_scope

logger = structlog.get_logger(__name__)


async def run_health_check(workspace_id: uuid.UUID, source_id: uuid.UUID) -> str:
    """Check one source and store the outcome. Returns its health status."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            source = await service.check_health(await service.get(source_id))
            await session.commit()
            return source.health_status.value


async def check_activated_sources() -> dict[str, int]:
    """Every activated source, one after the other. One failure stops nothing."""
    with system_scope():
        async with session_factory() as session:
            targets = await activated_sources(session)
    outcome: dict[str, int] = {}
    for workspace_id, source_id in targets:
        try:
            status = await run_health_check(workspace_id, source_id)
        except Exception:
            logger.exception("source_health_check_crashed", source_id=str(source_id))
            status = "crashed"
        outcome[status] = outcome.get(status, 0) + 1
    logger.info("source_health_checks_completed", **outcome)
    return outcome


def run_health_checks() -> dict[str, int]:
    """Entry point for RQ, which is synchronous. Scheduled in leka.background.schedule."""
    return asyncio.run(check_activated_sources())
