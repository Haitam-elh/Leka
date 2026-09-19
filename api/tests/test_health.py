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
    from leka.core import health

    assert health.PROBE_TIMEOUT_SECONDS <= 5
