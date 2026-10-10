"""The authorisation model (LEKA-402), pure: one function decides whether a
person may do something — to a resource or not — and says why, the same way
everywhere.

    who      a person, their role in this workspace, its lifecycle state
    what     a permission (docs/permissions.md), or an action named by a
             module (agent:run, workflow:run…) under the permission it needs
    on what  a resource: its type, its id, who it belongs to, whether it is
             a restricted entity

    in order, the first that refuses decides:
      1. the workspace     awaiting deletion: nothing · suspended: no write
      2. the role          it carries the permission, or it does not
      3. the owner         a resource someone else owns needs the permission
                           that reaches anyone's (`anyones`), when one does
      4. the restriction   a restricted entity is only for a role that may
                           read restricted entities

Every decision says its rule and its reason, so that a refusal reads the
same in the API, in the trail of decisions (AccessDecision) and in a test.
Nothing here reads a database: the service records, the dependencies
translate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from leka.governance.schemas import (
    ROLE_PERMISSIONS,
    WRITE_PERMISSIONS,
    Permission,
    Principal,
)
from leka.platform import Role, WorkspaceStatus


@dataclass(frozen=True)
class Subject:
    """Who asks: as the policy reads them."""

    user_id: uuid.UUID
    role: Role
    workspace_status: WorkspaceStatus = WorkspaceStatus.ACTIVE

    @classmethod
    def of(cls, principal: Principal) -> Subject:
        return cls(principal.user_id, principal.role, principal.workspace_status)

    @property
    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[self.role]


@dataclass(frozen=True)
class Resource:
    """What it is asked on."""

    type: str  # entity, intention, context, capability, agent_run, workflow_run…
    id: str | None = None
    # Who it belongs to, when that changes who may act on it.
    owner_id: uuid.UUID | None = None
    # An entity an admin restricted (LEKA-402).
    restricted: bool = False


@dataclass(frozen=True)
class Decision:
    allowed: bool
    # workspace · role · owner · restriction
    rule: str
    # allowed: role_grants, owner, read_restricted · refused:
    # workspace_unavailable, workspace_suspended, role_lacks_permission,
    # not_owner, restricted
    reason: str
    permission: Permission
    message: str = ""


def _refused(rule: str, reason: str, permission: Permission, message: str) -> Decision:
    return Decision(False, rule, reason, permission, message)


def evaluate(
    subject: Subject,
    permission: Permission,
    resource: Resource | None = None,
    *,
    anyones: Permission | None = None,
) -> Decision:
    """Whether `subject` may use `permission` — on `resource` when given —
    and why. `anyones`: the permission that lets one act on what someone
    else owns (intention:approve for another's run, context:manage for
    another's context)."""
    status = subject.workspace_status
    if status is WorkspaceStatus.PENDING_DELETION:
        return _refused(
            "workspace",
            "workspace_unavailable",
            permission,
            "This workspace is scheduled for deletion and is no longer "
            "accessible. Contact support during the grace period to restore it.",
        )
    if status is WorkspaceStatus.SUSPENDED and permission in WRITE_PERMISSIONS:
        return _refused(
            "workspace",
            "workspace_suspended",
            permission,
            "This workspace is suspended: your data is intact and readable, "
            "but changes are paused until the account is reactivated.",
        )
    granted = subject.permissions
    if permission not in granted:
        return _refused(
            "role",
            "role_lacks_permission",
            permission,
            f"Your role in this workspace ({subject.role.value}) does not allow "
            f"{permission.value}.",
        )
    reason = "role_grants"
    if resource is not None and resource.owner_id is not None:
        if resource.owner_id == subject.user_id:
            reason = "owner"
        elif anyones is not None and anyones not in granted:
            return _refused(
                "owner",
                "not_owner",
                permission,
                f"This {resource.type} is someone else's: it takes {anyones.value}.",
            )
    if resource is not None and resource.restricted:
        if Permission.ENTITY_READ_RESTRICTED not in granted:
            return _refused(
                "restriction",
                "restricted",
                permission,
                "This is restricted to the workspace's administrators.",
            )
        reason = "read_restricted"
    return Decision(True, "role" if reason == "role_grants" else reason, reason, permission)


def sees_restricted(role: Role) -> bool:
    """Whether a role sees restricted entities — the rest never do."""
    return Permission.ENTITY_READ_RESTRICTED in ROLE_PERMISSIONS[role]
