"""Authorisation decisions, in one place.

Everything here answers a yes/no question about a Principal. Nothing here
touches HTTP: the FastAPI dependencies in dependencies.py translate these
answers into status codes, so the rules stay testable without a request.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core.request_context import current_request_id
from leka.db import session_factory, workspace_scope
from leka.governance.models import AccessDecision, EntityRestriction
from leka.governance.policy import Decision, Resource, Subject, evaluate, sees_restricted
from leka.governance.repository import AuditRepository, RestrictionRepository
from leka.governance.schemas import (
    WRITE_PERMISSIONS,
    Permission,
    Principal,
)
from leka.platform import MembershipResolver, Role, WorkspaceStatus

logger = structlog.get_logger(__name__)


class AuthorisationError(Exception):
    """The request is refused. Carries why, so the API can say so."""

    def __init__(self, reason: str, *, status_code: int = 403) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class WorkspaceSuspendedError(AuthorisationError):
    """Reads are allowed, this write is not."""


class WorkspaceUnavailableError(AuthorisationError):
    """The workspace is awaiting deletion. Nothing is allowed."""


def check_lifecycle(principal: Principal, permission: Permission) -> None:
    """Enforce the workspace's lifecycle state.

    Called from one dependency, never from a route. A status check repeated
    across forty routes is a status check missing from one of them — and the
    one it is missing from is the one that lets a suspended customer keep
    writing.

    A refusal here is 403 with a reason, never 404. A customer whose invoice
    bounced must not be told their data no longer exists.
    """
    if principal.workspace_status is WorkspaceStatus.PENDING_DELETION:
        msg = (
            "This workspace is scheduled for deletion and is no longer "
            "accessible. Contact support during the grace period to restore it."
        )
        raise WorkspaceUnavailableError(msg)

    if principal.workspace_status is WorkspaceStatus.SUSPENDED and permission in WRITE_PERMISSIONS:
        msg = (
            "This workspace is suspended: your data is intact and readable, "
            "but changes are paused until the account is reactivated."
        )
        raise WorkspaceSuspendedError(msg)


def check_permission(principal: Principal, permission: Permission) -> None:
    """Does this role carry this permission?"""
    if not principal.has(permission):
        msg = (
            f"Your role in this workspace ({principal.role.value}) does not "
            f"allow {permission.value}."
        )
        raise AuthorisationError(msg)


def check_role(principal: Principal, minimum: Role) -> None:
    """Is this role at or above the required one?"""
    if not principal.outranks_or_equals(minimum):
        msg = (
            f"This action requires the {minimum.value} role or above; yours is "
            f"{principal.role.value}."
        )
        raise AuthorisationError(msg)


class GovernanceService:
    """Answers "may this principal do this?" and records that it was asked."""

    def __init__(
        self,
        memberships: MembershipResolver,
        audit: AuditRepository,
    ) -> None:
        self._memberships = memberships
        self._audit = audit

    def authorise(self, principal: Principal, permission: Permission) -> None:
        """The full check, in the order that produces the clearest refusal.

        Lifecycle first: telling an admin of a suspended workspace that they
        lack a permission would send them looking for the wrong problem.
        """
        check_lifecycle(principal, permission)
        check_permission(principal, permission)

    async def can_demote_or_remove(self, principal: Principal, target_role: Role) -> bool:
        """Refuse removing or demoting the last owner.

        A workspace with no owner cannot be deleted, transferred or rescued —
        it is a support ticket waiting to happen, created by a single
        careless click.
        """
        if target_role is not Role.OWNER:
            return True
        membership = await self._memberships.get_for_user_in_workspace(
            principal.user_id, principal.workspace_id
        )
        return membership is not None


# ── LEKA-402: what a person may see, and what was decided ──────────────────


async def hidden_on_behalf(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID | None
) -> frozenset[uuid.UUID]:
    """What work done for this person — an agent, a workflow, an analysis —
    must not see: what their role, now, may not. Nobody: the restricted, all
    of them."""
    seat = (
        await MembershipResolver(session).get_for_user_in_workspace(user_id, workspace_id)
        if user_id is not None
        else None
    )
    if seat is None:
        return await RestrictionRepository(session, workspace_id).restricted_ids()
    return await hidden_for(session, workspace_id, seat.role)


async def hidden_for(
    session: AsyncSession, workspace_id: uuid.UUID, role: Role
) -> frozenset[uuid.UUID]:
    """The entities a role may not see in this workspace: the restricted
    ones, unless it may read them."""
    if sees_restricted(role):
        return frozenset()
    return await RestrictionRepository(session, workspace_id).restricted_ids()


def decision_row(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    role: Role,
    decision: Decision,
    *,
    action: str | None = None,
    resource: Resource | None = None,
    route: str | None = None,
    detail: Mapping[str, object] | None = None,
) -> AccessDecision:
    return AccessDecision(
        workspace_id=workspace_id,
        id=uuid.uuid4(),
        user_id=user_id,
        action=(action or decision.permission.value)[:60],
        permission=decision.permission.value,
        resource_type=resource.type if resource is not None else None,
        resource_id=resource.id[:100] if resource is not None and resource.id else None,
        decision="allow" if decision.allowed else "deny",
        rule=decision.rule,
        reason=decision.reason,
        role=role.value,
        request_id=current_request_id(),
        route=route[:200] if route else None,
        at=datetime.now(UTC),
        detail=dict(detail or {}),
    )


def worth_keeping(decision: Decision) -> bool:
    """What the trail keeps: every refusal, every write or run allowed —
    not every read, which would bury the rest."""
    return not decision.allowed or decision.permission in WRITE_PERMISSIONS


def record(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    role: Role,
    decision: Decision,
    **said: object,
) -> None:
    """Kept with what it allowed: committed, or not, with the change."""
    session.add(decision_row(workspace_id, user_id, role, decision, **said))  # type: ignore[arg-type]


async def record_apart(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    role: Role,
    decision: Decision,
    **said: object,
) -> None:
    """Kept on its own, committed now: a refusal ends the request, and its
    transaction is rolled back — the refusal must not be."""
    try:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                session.add(decision_row(workspace_id, user_id, role, decision, **said))  # type: ignore[arg-type]
                await session.commit()
    except Exception:
        # Refusing stays refusing: a trail that cannot be written is logged,
        # never a reason to let the request through.
        logger.exception("access_decision_unrecorded", reason=decision.reason)


async def authorize(
    session: AsyncSession,
    principal: Principal,
    permission: Permission,
    *,
    action: str,
    resource: Resource | None = None,
    anyones: Permission | None = None,
) -> Decision:
    """An execution decided before it starts — an agent, a workflow, a
    capability — and kept either way: allowed, with what it starts; refused,
    on its own."""
    decided = evaluate(Subject.of(principal), permission, resource, anyones=anyones)
    said: dict[str, object] = {"action": action, "resource": resource}
    if decided.allowed:
        record(session, principal.workspace_id, principal.user_id, principal.role, decided, **said)
    else:
        await record_apart(
            principal.workspace_id, principal.user_id, principal.role, decided, **said
        )
    return decided


class RestrictionService:
    """Entities restricted, and back (LEKA-402)."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._restrictions = RestrictionRepository(session, workspace_id)

    async def all(self) -> list[EntityRestriction]:
        return list(await self._restrictions.all())

    async def restrict(
        self, entity_id: uuid.UUID, *, reason: str, by: uuid.UUID
    ) -> EntityRestriction:
        """Restricted, saying why — said again, its reason is the new one."""
        row = await self._restrictions.of(entity_id)
        if row is None:
            row = EntityRestriction(
                workspace_id=self._workspace_id,
                id=uuid.uuid4(),
                entity_id=entity_id,
                reason=reason,
                restricted_by=by,
                restricted_at=datetime.now(UTC),
            )
            self._restrictions.add(row)
        else:
            row.reason = reason
            row.restricted_by = by
        await self._session.flush()
        return row

    async def lift(self, entity_id: uuid.UUID) -> bool:
        row = await self._restrictions.of(entity_id)
        if row is None:
            return False
        await self._restrictions.remove(row)
        await self._session.flush()
        return True
