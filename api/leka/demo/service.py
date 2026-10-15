"""A person's demonstration: found, made, or made afresh (LEKA-449)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import SourceService
from leka.connectors.demo import SOURCES
from leka.db import workspace_scope
from leka.demo.repository import DemoRepository
from leka.platform import Workspace, WorkspaceRepository, WorkspaceService

DEMO_NAME = "Nova Retail (démo)"


class DemoService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workspaces = WorkspaceService(WorkspaceRepository(session), session)
        self._demos = DemoRepository(session)

    async def mine(self, user_id: uuid.UUID) -> Workspace | None:
        return await self._demos.owned_by(user_id)

    async def open(
        self, user_id: uuid.UUID, *, language: str | None = None, fresh: bool = False
    ) -> tuple[Workspace, bool]:
        """Theirs, and whether it was made now. `fresh`: the one before is
        erased, a new one made — a clean state."""
        known = await self.mine(user_id)
        if known is not None and not fresh:
            return known, False
        if known is not None:
            await self._workspaces.erase(known)
        workspace = await self._workspaces.create(
            DEMO_NAME, owner_user_id=user_id, default_language=language
        )
        workspace.demo = True
        await self._session.flush()
        with workspace_scope(workspace.id):
            sources = SourceService(self._session, workspace.id, actor_user_id=user_id)
            for kind, name, config, credentials in SOURCES:
                source = await sources.create(kind, name, config, credentials)
                _, failed = await sources.test(source)
                if failed is not None:  # pragma: no cover - a replayed source always answers
                    raise RuntimeError(failed.message)
                # Its first pass starts once this is committed, as a customer's.
                await sources.activate(source)
        return workspace, True
