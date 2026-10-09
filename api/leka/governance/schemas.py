"""Authorisation vocabulary: who is asking, and what they may do.

Roles and memberships are tenancy and live in leka.platform. What a role is
ALLOWED to do is policy, and lives here.

The matrix below is the single source of truth for docs/permissions.md. A
permission table that exists only in prose drifts from the code within a
month; this one cannot, because the tests read it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from leka.platform import Role, WorkspaceStatus


class Permission(enum.StrEnum):
    """One thing a member may attempt.

    Named after the action, not after the route: routes get renamed, and a
    permission called `patch_workspace_current` would have to be renamed with
    them.
    """

    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"
    WORKSPACE_TRANSFER = "workspace:transfer"

    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_UPDATE_ROLE = "member:update_role"
    MEMBER_REMOVE = "member:remove"

    SOURCE_READ = "source:read"
    SOURCE_MANAGE = "source:manage"

    INTENTION_READ = "intention:read"
    INTENTION_CREATE = "intention:create"
    INTENTION_APPROVE = "intention:approve"

    # Archive, or change how it follows the model, a context someone else
    # made (LEKA-376). Their own, any member may.
    CONTEXT_MANAGE = "context:manage"

    JOB_READ = "job:read"

    # Entity-level access (LEKA-402): mark an entity restricted, see one,
    # and read the trail of access decisions.
    ENTITY_RESTRICT = "entity:restrict"
    ENTITY_READ_RESTRICTED = "entity:read_restricted"
    ACCESS_READ = "access:read"


# Roles are a chain: an owner can do everything an admin can, an admin
# everything a member can. Expressed as ranks so that require_role(ADMIN)
# means "admin or above" and nobody has to remember to list OWNER too — the
# forgotten OWNER in the fourteenth route is exactly the bug this avoids.
ROLE_RANK: dict[Role, int] = {
    Role.MEMBER: 0,
    Role.ADMIN: 1,
    Role.OWNER: 2,
}

_MEMBER_PERMISSIONS = frozenset(
    {
        Permission.WORKSPACE_READ,
        Permission.MEMBER_READ,
        Permission.SOURCE_READ,
        Permission.INTENTION_READ,
        Permission.INTENTION_CREATE,
    }
)

_ADMIN_PERMISSIONS = _MEMBER_PERMISSIONS | {
    Permission.WORKSPACE_UPDATE,
    Permission.MEMBER_INVITE,
    Permission.MEMBER_UPDATE_ROLE,
    Permission.MEMBER_REMOVE,
    Permission.SOURCE_MANAGE,
    Permission.INTENTION_APPROVE,
    Permission.CONTEXT_MANAGE,
    Permission.JOB_READ,
    Permission.ENTITY_RESTRICT,
    Permission.ENTITY_READ_RESTRICTED,
    Permission.ACCESS_READ,
}

# Only an owner deletes the workspace or hands it over. An admin managing
# members must not be able to end the company's account.
_OWNER_PERMISSIONS = _ADMIN_PERMISSIONS | {
    Permission.WORKSPACE_DELETE,
    Permission.WORKSPACE_TRANSFER,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.MEMBER: _MEMBER_PERMISSIONS,
    Role.ADMIN: _ADMIN_PERMISSIONS,
    Role.OWNER: _OWNER_PERMISSIONS,
}

# Permissions that change something. A suspended workspace refuses these and
# allows the rest: an unpaid invoice should not look like data loss.
WRITE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.WORKSPACE_UPDATE,
        Permission.WORKSPACE_DELETE,
        Permission.WORKSPACE_TRANSFER,
        Permission.MEMBER_INVITE,
        Permission.MEMBER_UPDATE_ROLE,
        Permission.MEMBER_REMOVE,
        Permission.SOURCE_MANAGE,
        Permission.INTENTION_CREATE,
        Permission.INTENTION_APPROVE,
        Permission.CONTEXT_MANAGE,
        Permission.ENTITY_RESTRICT,
    }
)


class Principal(BaseModel):
    """Who is making this request, in which workspace, with what role.

    Built server side on every request: the user from LEKA-330's seam, the
    workspace from the server-side session, the role from a live read of the
    memberships table.

    The role is NOT carried in the session. Freezing it at sign-in would mean
    that removing someone from a workspace leaves them in until they happen
    to log out — which is not a revocation, it is a delay.
    """

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: Role
    workspace_status: WorkspaceStatus

    @property
    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[self.role]

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def outranks_or_equals(self, role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


# ── LEKA-402: the model, restrictions, decisions ───────────────────────────


class RolePermissionsRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    permissions: list[Permission]


class AccessModelRead(BaseModel):
    """Who may do what here: every role's permissions, and the reader's."""

    model_config = ConfigDict(frozen=True)

    roles: list[RolePermissionsRead]
    permissions: list[Permission]
    writes: list[Permission] = Field(description="Refused while the workspace is suspended.")
    mine: list[Permission]
    role: Role


class RestrictionUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(min_length=3, max_length=500, description="Why it is restricted.")


class RestrictionRead(BaseModel):
    """An entity only the workspace's administrators see."""

    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID
    name: str | None = Field(description="Its name; none when it left the model.")
    type: str | None
    reason: str
    restricted_by: uuid.UUID | None
    restricted_at: datetime


class AccessDecisionRead(BaseModel):
    """One access decision kept."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    at: datetime
    user_id: uuid.UUID | None
    role: str
    action: str
    permission: str
    resource_type: str | None
    resource_id: str | None
    decision: Literal["allow", "deny"]
    rule: str = Field(description="workspace, role, owner, restriction")
    reason: str
    route: str | None
    request_id: str | None
