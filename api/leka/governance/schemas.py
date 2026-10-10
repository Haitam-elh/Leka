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
from typing import Any, Literal

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

    # Roles of the workspace's own, and its policies (LEKA-403).
    POLICY_MANAGE = "policy:manage"

    # The audit trail (LEKA-407): searched and read; how long it is kept —
    # the owner's alone.
    AUDIT_READ = "audit:read"
    AUDIT_MANAGE = "audit:manage"


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
    Permission.POLICY_MANAGE,
    Permission.AUDIT_READ,
}

# Only an owner deletes the workspace or hands it over. An admin managing
# members must not be able to end the company's account.
_OWNER_PERMISSIONS = _ADMIN_PERMISSIONS | {
    Permission.WORKSPACE_DELETE,
    Permission.WORKSPACE_TRANSFER,
    # How long the trail is kept: shortening it erases evidence (LEKA-407).
    Permission.AUDIT_MANAGE,
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
        Permission.POLICY_MANAGE,
        Permission.AUDIT_MANAGE,
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

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: Role
    workspace_status: WorkspaceStatus
    # A role of the workspace's own (LEKA-403): its key, and what it grants —
    # its base role's permissions, with what it adds and less what it takes
    # away. None: the base role's, as the matrix says.
    custom_role: str | None = None
    granted: frozenset[Permission] | None = None
    # The workspace's policies in force (governance.policy.Rule), read on this
    # request like the role.
    policies: tuple[Any, ...] = ()

    @property
    def permissions(self) -> frozenset[Permission]:
        return self.granted if self.granted is not None else ROLE_PERMISSIONS[self.role]

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
    custom_role: str | None = Field(default=None, description="A role of the workspace's own.")


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


# ── LEKA-403: roles of the workspace's own, policies, their history ────────


class RoleUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    base: Literal["member", "admin"]
    added: list[str] = Field(default_factory=list, description="Permissions it adds to its base.")
    removed: list[str] = Field(
        default_factory=list, description="Permissions of its base it takes away."
    )


class RoleRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    description: str | None
    base: Literal["member", "admin"]
    added: list[str]
    removed: list[str]
    permissions: list[Permission] = Field(
        description="What it grants: inherited, added, less removed."
    )
    holders: int


class AssignmentUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str | None = Field(description="A role of the workspace's own; none: their seat's.")


class AssignmentRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    role: str


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    effect: Literal["deny", "allow"]
    actions: list[str] = Field(
        min_length=1, description="Permissions, or agent:run, workflow:run; * for every one."
    )
    roles: list[str] = Field(
        default_factory=list,
        description="member, admin, owner or a role of the workspace's own; none: everyone.",
    )
    resource_types: list[str] = Field(default_factory=list)
    risk_at_least: Literal["low", "medium", "high", "critical"] | None = None
    kinds: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)
    enabled: bool = True


class PolicyRead(PolicyUpdate):
    id: uuid.UUID
    updated_at: datetime


class GovernanceEventRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    subject_type: Literal["role", "policy", "assignment", "ai_control", "protection"]
    subject_id: str
    kind: str
    by: uuid.UUID | None
    at: datetime
    before: dict[str, object] | None
    after: dict[str, object] | None


class EvaluationAsk(BaseModel):
    """A decision, asked without doing anything: as this role would be
    answered, under the policies in force."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["member", "admin", "owner"] = "member"
    custom_role: str | None = None
    permission: str
    action: str | None = None
    resource_type: str | None = None
    risk: Literal["low", "medium", "high"] | None = None
    kind: str | None = None
    category: str | None = None


class EvaluationRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    rule: str
    reason: str
    policy: str | None
    message: str


# ── AI governance (LEKA-406) ───────────────────────────────────────────────

AIControlKind = Literal["model_access", "usage_limit", "output_check", "approval"]
Risk = Literal["low", "medium", "high"]


class AIControlUpdate(BaseModel):
    """A control on the workspace's AI: its kind's settings are read, the
    others left aside."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    kind: AIControlKind
    purposes: list[str] = Field(
        default_factory=list,
        description="The work it covers, as patterns: agent:*, intention.*; none: all of it.",
    )
    roles: list[str] = Field(
        default_factory=list,
        description="member, admin, owner or a role of the workspace's own; none: everyone.",
    )
    enabled: bool = True
    # model_access
    providers: list[str] = Field(default_factory=list, description="none: any provider.")
    owners: list[Literal["leka", "workspace"]] = Field(
        default_factory=list, description="Whose account: LEKA's, the workspace's; none: either."
    )
    block: bool = Field(default=False, description="No model at all.")
    # usage_limit
    period: Literal["day", "month"] = "day"
    per: Literal["workspace", "person"] = "workspace"
    max_calls: int | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)
    # output_check
    detect: list[Literal["secrets", "personal_data"]] = Field(default_factory=list)
    on_finding: Literal["redact", "block", "flag"] = "redact"
    # approval
    risk_at_least: Risk = "high"


class AIControlRead(AIControlUpdate):
    id: uuid.UUID
    updated_at: datetime


class AIControlEventRead(BaseModel):
    """What a control did, once — what it found, never the text."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    control_id: uuid.UUID | None
    control_name: str | None
    kind: AIControlKind
    outcome: Literal[
        "refused", "limited", "redacted", "blocked", "flagged", "held", "approved", "rejected"
    ]
    purpose: str | None
    ref: str | None
    run_id: uuid.UUID | None
    user_id: uuid.UUID | None
    provider: str | None
    model: str | None
    at: datetime
    detail: dict[str, object]


# ── the audit trail (LEKA-407) ─────────────────────────────────────────────

AuditCategory = Literal[
    "user",
    "team",
    "workspace",
    "data",
    "access",
    "governance",
    "decision",
    "action",
    "ai",
    "audit",
]


class AuditEventRead(BaseModel):
    """One event of the audit trail: who, when, what, to what, the outcome,
    from where — and what else it said."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    at: datetime
    category: AuditCategory
    action: str
    outcome: Literal["success", "failure", "denied"]
    actor_type: Literal["user", "system"]
    actor_id: uuid.UUID | None
    actor_role: str | None
    target_type: str | None
    target_id: str | None
    target_label: str | None
    request_id: str | None
    ip: str | None = Field(description="A network prefix, never a full address.")
    user_agent: str | None
    detail: dict[str, object]


class AuditPageRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: list[AuditEventRead]
    next: str | None = Field(description="Reads on from the last event; none: the end.")


class AuditEventDetail(AuditEventRead):
    related: list[AuditEventRead] = Field(description="What else the same request did.")


class AuditSettingsRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    retention_days: int
    default_days: int
    min_days: int
    max_days: int
    oldest: datetime | None = Field(description="The oldest event still kept.")
    updated_at: datetime | None
    updated_by: uuid.UUID | None


class AuditSettingsUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    retention_days: int = Field(ge=90, le=2555)
