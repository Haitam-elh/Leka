"""The health endpoint must reflect reality, not process liveness."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_health_reports_every_backing_service(client: AsyncClient, api_prefix: str) -> None:
    response = await client.get(f"{api_prefix}/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["services"] == {"database": True, "redis": True}


async def test_health_probes_are_bounded(client: AsyncClient, api_prefix: str) -> None:
    """An unreachable dependency must read as "down", never as a hung request."""
    from leka.platform import health

    assert health.PROBE_TIMEOUT_SECONDS <= 5


async def test_caddy_routes_on_the_process_answering(client: AsyncClient, api_prefix: str) -> None:
    """2026-11-07: Caddy took the only API out when the database was slow,
    and every page answered 503. It routes on liveness: no backing service."""
    response = await client.get(f"{api_prefix}/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "services": {}}


async def test_the_apis_queries_are_cut_past_their_limit() -> None:
    """A runaway query is cut by PostgreSQL, never left to starve the
    database (2026-11-07: one ran 310 s)."""
    from sqlalchemy import text

    from leka.db import engine
    from leka.main import STATEMENT_TIMEOUT_MS

    async with engine.connect() as connection:
        said = (
            await connection.execute(
                text("SELECT setting::int FROM pg_settings WHERE name = 'statement_timeout'")
            )
        ).scalar()
    assert said == STATEMENT_TIMEOUT_MS
