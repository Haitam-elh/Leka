"""Shared fixtures.

Importing leka.main reads the environment, so these tests need
LEKA_DATABASE_URL, LEKA_REDIS_URL and LEKA_SECRET_KEY set — exactly like the
application does. That is the point: a test suite that runs without a valid
environment would not be testing what production runs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core.config import settings
from leka.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client wired straight to the ASGI app — no network, no port."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def api_prefix() -> str:
    return settings.api_v1_prefix


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A database session whose workspaces are deleted afterwards.

    Deleting the workspaces is enough: every business table cascades from
    them, which is itself part of what the schema promises.
    """
    from sqlalchemy import select

    from leka.db import session_factory
    from leka.platform import Workspace

    async with session_factory() as db_session:
        created_before = {
            workspace.id for workspace in (await db_session.execute(select(Workspace))).scalars()
        }
        try:
            yield db_session
        finally:
            await db_session.rollback()
            async with session_factory() as cleanup:
                for workspace in (await cleanup.execute(select(Workspace))).scalars().all():
                    if workspace.id not in created_before:
                        await cleanup.delete(workspace)
                await cleanup.commit()
