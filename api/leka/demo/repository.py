"""Where a person's demonstration is found."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.db import system_scope
from leka.platform import Membership, Role, Workspace


class DemoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def owned_by(self, user_id: uuid.UUID) -> Workspace | None:
        """The demonstration this person owns, if they opened one."""
        # Across tenants along one axis: this person's own seats.
        with system_scope():
            found = await self._session.scalars(
                select(Workspace)
                .join(Membership, Membership.workspace_id == Workspace.id)
                .where(
                    Membership.user_id == user_id,
                    Membership.role == Role.OWNER,
                    Workspace.demo.is_(True),
                )
                .limit(1)
            )
            return found.first()
