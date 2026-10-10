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

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.governance.models import (
    AccessDecision,
    AIControl,
    AIControlEvent,
    EntityRestriction,
    GovernanceEvent,
    RoleAssignment,
    WorkspacePolicy,
    WorkspaceRole,
)


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


class PolicyRepository:
    """One workspace's roles of its own, who holds them, its policies, and
    the history of their changes (LEKA-403)."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def add(self, row: WorkspaceRole | RoleAssignment | WorkspacePolicy | GovernanceEvent) -> None:
        self._session.add(row)

    async def remove(self, row: WorkspaceRole | RoleAssignment | WorkspacePolicy) -> None:
        await self._session.delete(row)

    async def roles(self) -> Sequence[WorkspaceRole]:
        return (
            await self._session.scalars(
                select(WorkspaceRole)
                .where(WorkspaceRole.workspace_id == self._workspace_id)
                .order_by(WorkspaceRole.name)
            )
        ).all()

    async def role(self, key: str) -> WorkspaceRole | None:
        found: WorkspaceRole | None = await self._session.scalar(
            select(WorkspaceRole).where(
                WorkspaceRole.workspace_id == self._workspace_id, WorkspaceRole.key == key
            )
        )
        return found

    async def assignments(self) -> Sequence[RoleAssignment]:
        return (
            await self._session.scalars(
                select(RoleAssignment).where(RoleAssignment.workspace_id == self._workspace_id)
            )
        ).all()

    async def assignment(self, user_id: uuid.UUID) -> RoleAssignment | None:
        found: RoleAssignment | None = await self._session.scalar(
            select(RoleAssignment).where(
                RoleAssignment.workspace_id == self._workspace_id,
                RoleAssignment.user_id == user_id,
            )
        )
        return found

    async def held_role(self, user_id: uuid.UUID) -> WorkspaceRole | None:
        """The role of the workspace's own this person holds, if any."""
        found: WorkspaceRole | None = await self._session.scalar(
            select(WorkspaceRole)
            .join(
                RoleAssignment,
                (RoleAssignment.role_id == WorkspaceRole.id)
                & (RoleAssignment.workspace_id == WorkspaceRole.workspace_id),
            )
            .where(
                RoleAssignment.workspace_id == self._workspace_id,
                RoleAssignment.user_id == user_id,
            )
        )
        return found

    async def policies(self, *, enabled_only: bool = False) -> Sequence[WorkspacePolicy]:
        query = (
            select(WorkspacePolicy)
            .where(WorkspacePolicy.workspace_id == self._workspace_id)
            .order_by(WorkspacePolicy.priority.desc(), WorkspacePolicy.name)
        )
        if enabled_only:
            query = query.where(WorkspacePolicy.enabled.is_(True))
        return (await self._session.scalars(query)).all()

    async def policy(self, policy_id: uuid.UUID) -> WorkspacePolicy | None:
        found: WorkspacePolicy | None = await self._session.scalar(
            select(WorkspacePolicy).where(
                WorkspacePolicy.workspace_id == self._workspace_id,
                WorkspacePolicy.id == policy_id,
            )
        )
        return found

    async def history(
        self, *, subject_type: str | None = None, limit: int = 100
    ) -> Sequence[GovernanceEvent]:
        query = (
            select(GovernanceEvent)
            .where(GovernanceEvent.workspace_id == self._workspace_id)
            .order_by(GovernanceEvent.at.desc(), GovernanceEvent.id)
            .limit(limit)
        )
        if subject_type is not None:
            query = query.where(GovernanceEvent.subject_type == subject_type)
        return (await self._session.scalars(query)).all()


class AIControlRepository:
    """One workspace's AI controls, and what they did (LEKA-406)."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def add(self, row: AIControl | AIControlEvent) -> None:
        self._session.add(row)

    async def remove(self, row: AIControl) -> None:
        await self._session.delete(row)

    async def controls(self, *, enabled_only: bool = False) -> Sequence[AIControl]:
        query = (
            select(AIControl)
            .where(AIControl.workspace_id == self._workspace_id)
            .order_by(AIControl.kind, AIControl.name, AIControl.id)
        )
        if enabled_only:
            query = query.where(AIControl.enabled.is_(True))
        return (await self._session.scalars(query)).all()

    async def control(self, control_id: uuid.UUID) -> AIControl | None:
        found: AIControl | None = await self._session.scalar(
            select(AIControl).where(
                AIControl.workspace_id == self._workspace_id, AIControl.id == control_id
            )
        )
        return found

    async def events(
        self,
        *,
        outcome: str | None = None,
        run_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> Sequence[AIControlEvent]:
        query = (
            select(AIControlEvent)
            .where(AIControlEvent.workspace_id == self._workspace_id)
            .order_by(AIControlEvent.at.desc(), AIControlEvent.id)
            .limit(limit)
        )
        if outcome is not None:
            query = query.where(AIControlEvent.outcome == outcome)
        if run_id is not None:
            # An agent run's own: its calls are about it by their ref.
            query = query.where(
                or_(AIControlEvent.run_id == run_id, AIControlEvent.ref == f"agent_run:{run_id}")
            )
        return (await self._session.scalars(query)).all()
