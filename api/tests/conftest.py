"""Shared fixtures.

Importing leka.main reads the environment, so these tests need
LEKA_DATABASE_URL, LEKA_REDIS_URL and LEKA_SECRET_KEY set — exactly like the
application does. That is the point: a test suite that runs without a valid
environment would not be testing what production runs.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core.config import settings
from leka.main import app
from leka.platform import UserId, WorkspaceId, get_current_user_id, get_session_store

# ── LEKA-330's seam, implemented for tests ───────────────────────────────────
#
# LEKA-331's routes need to know who is calling and which workspace is
# active. Both come from LEKA-330, which does not exist yet. Rather than wait
# — or, worse, build a second authentication — the tests satisfy the seam's
# contract with the simplest thing that can.
#
# This is what the seam is for. When LEKA-330 lands, its real implementations
# replace these overrides and not one line of LEKA-331 changes. If that turns
# out not to be true, the contract was wrong, and better to find out here.


@dataclass
class FakeIdentity:
    """Who the next request comes from, and where it is.

    A test mutates these between calls the way a real session would change
    between sign-ins and switches.
    """

    user_id: uuid.UUID | None = None
    active_workspace: uuid.UUID | None = None
    # What set_active_workspace was asked to do, in order. Lets a test assert
    # that a refused switch left the session untouched.
    switches: list[uuid.UUID] = field(default_factory=list)

    async def current_user_id(self, request: Request) -> UserId:
        if self.user_id is None:
            msg = "no signed-in user in this test"
            raise RuntimeError(msg)
        return UserId(self.user_id)

    async def get_active_workspace(self, request: Request) -> WorkspaceId | None:
        if self.active_workspace is None:
            return None
        return WorkspaceId(self.active_workspace)

    async def set_active_workspace(self, request: Request, workspace_id: WorkspaceId) -> None:
        self.switches.append(workspace_id)
        self.active_workspace = workspace_id

    def sign_in(self, user_id: uuid.UUID, workspace_id: uuid.UUID | None = None) -> None:
        self.user_id = user_id
        self.active_workspace = workspace_id


@pytest.fixture
def identity() -> Iterator[FakeIdentity]:
    """LEKA-330's seam, implemented for tests.

    Overrides the two dependencies LEKA-331 consumes. Removed afterwards, so
    a test that forgets to sign in gets the real dependency and its
    NotImplementedError rather than the previous test's user.
    """
    fake = FakeIdentity()
    app.dependency_overrides[get_current_user_id] = fake.current_user_id
    app.dependency_overrides[get_session_store] = lambda: fake

    yield fake

    app.dependency_overrides.pop(get_current_user_id, None)
    app.dependency_overrides.pop(get_session_store, None)


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
