"""Authorisation decisions, in one place.

Everything here answers a yes/no question about a Principal. Nothing here
touches HTTP: the FastAPI dependencies in dependencies.py translate these
answers into status codes, so the rules stay testable without a request.
"""

from __future__ import annotations

from leka.governance.repository import AuditRepository
from leka.governance.schemas import (
    WRITE_PERMISSIONS,
    Permission,
    Principal,
)
from leka.platform import MembershipResolver, Role, WorkspaceStatus


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
