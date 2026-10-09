"""Database access for the governance module.

The only place in this module where a query is written (architecture rule 4).

Membership queries are NOT here: leka.platform owns the Membership model, and
the module that owns a model owns its queries. Governance imports
MembershipResolver from there rather than writing a second set of queries
that would drift from the first.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.governance.models import AccessDecision, EntityRestriction


class AuditRepository:
    """Appends to the audit trail and reads it back.

    Append-only by intent: a row is written when something happens and never
    updated. An audit log that can be edited is not an audit log.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, row: AccessDecision) -> None:
        self._session.add(row)

    async def decisions(
        self,
        workspace_id: uuid.UUID,
        *,
        decision: str | None = None,
        user_id: uuid.UUID | None = None,
        action: str | None = None,
        before: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[AccessDecision]:
        """The workspace's access decisions, the latest first."""
        query = (
            select(AccessDecision)
            .where(AccessDecision.workspace_id == workspace_id)
            .order_by(AccessDecision.at.desc(), AccessDecision.id)
            .limit(limit)
        )
        if decision is not None:
            query = query.where(AccessDecision.decision == decision)
        if user_id is not None:
            query = query.where(AccessDecision.user_id == user_id)
        if action is not None:
            query = query.where(AccessDecision.action == action)
        if before is not None:
            query = query.where(AccessDecision.at < before)
        return (await self._session.scalars(query)).all()


class RestrictionRepository:
    """The entities one workspace restricted (LEKA-402)."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def restricted_ids(self) -> frozenset[uuid.UUID]:
        rows = await self._session.scalars(
            select(EntityRestriction.entity_id).where(
                EntityRestriction.workspace_id == self._workspace_id
            )
        )
        return frozenset(rows)

    async def all(self) -> Sequence[EntityRestriction]:
        return (
            await self._session.scalars(
                select(EntityRestriction)
                .where(EntityRestriction.workspace_id == self._workspace_id)
                .order_by(EntityRestriction.restricted_at.desc())
            )
        ).all()

    async def of(self, entity_id: uuid.UUID) -> EntityRestriction | None:
        found: EntityRestriction | None = await self._session.scalar(
            select(EntityRestriction).where(
                EntityRestriction.workspace_id == self._workspace_id,
                EntityRestriction.entity_id == entity_id,
            )
        )
        return found

    def add(self, row: EntityRestriction) -> None:
        self._session.add(row)

    async def remove(self, row: EntityRestriction) -> None:
        await self._session.delete(row)
