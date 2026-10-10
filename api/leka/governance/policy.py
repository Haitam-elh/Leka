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
      2. the role          it carries the permission, or it does not — a
                           role of the workspace's own (LEKA-403) carries its
                           base role's, with what it adds, less what it takes
                           away: taking away wins
      3. the policies      the workspace's rules (LEKA-403) for this action,
                           this person, this resource: the one of the highest
                           priority decides; at the same priority, a refusal
                           wins. A policy only takes away — an exception
                           (`allow`) lifts a refusal of lower priority, never
                           grants what the role does not carry
      4. the owner         a resource someone else owns needs the permission
                           that reaches anyone's (`anyones`), when one does
      5. the restriction   a restricted entity is only for a role that may
                           read restricted entities

Every decision says its rule and its reason, so that a refusal reads the
same in the API, in the trail of decisions (AccessDecision) and in a test.
Nothing here reads a database: the service records, the dependencies
translate.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from leka.governance.schemas import (
    ROLE_PERMISSIONS,
    WRITE_PERMISSIONS,
    Permission,
    Principal,
)
from leka.platform import Role, WorkspaceStatus

# ── roles of the workspace's own (LEKA-403) ────────────────────────────────

# What only an owner may do: no role of the workspace's own grants it.
OWNER_ONLY = frozenset({Permission.WORKSPACE_DELETE, Permission.WORKSPACE_TRANSFER})
# What every role keeps: a role that cannot read the workspace locks its
# holder out of it.
KEPT = frozenset({Permission.WORKSPACE_READ})
BASES = (Role.MEMBER, Role.ADMIN)


class RoleError(ValueError):
    """A role that cannot be what it says."""


@dataclass(frozen=True)
class CustomRole:
    """A role of the workspace's own: a base role, with what it adds and
    what it takes away."""

    key: str
    name: str
    base: Role
    added: frozenset[Permission] = frozenset()
    removed: frozenset[Permission] = frozenset()

    @property
    def permissions(self) -> frozenset[Permission]:
        """Inherited, then added, then taken away: taking away wins."""
        return (ROLE_PERMISSIONS[self.base] | self.added) - self.removed


def checked_role(role: CustomRole) -> CustomRole:
    """It, as it can be: on a member's or an admin's base; adding nothing
    only an owner may, nothing its base already has; taking away only what
    its base has, never reading the workspace; never adding and taking
    away the same."""
    if role.base not in BASES:
        msg = "a role is built on the member's or the admin's"
        raise RoleError(msg)
    base = ROLE_PERMISSIONS[role.base]
    if role.added & OWNER_ONLY:
        msg = f"only an owner may {', '.join(sorted(p.value for p in role.added & OWNER_ONLY))}"
        raise RoleError(msg)
    if role.added & base:
        msg = f"its base already grants {', '.join(sorted(p.value for p in role.added & base))}"
        raise RoleError(msg)
    if role.removed - base:
        msg = f"its base does not grant {', '.join(sorted(p.value for p in role.removed - base))}"
        raise RoleError(msg)
    if role.removed & KEPT:
        msg = "every role reads the workspace"
        raise RoleError(msg)
    if role.added & role.removed:
        msg = "a permission is added or taken away, not both"
        raise RoleError(msg)
    return role


# ── policies (LEKA-403) ─────────────────────────────────────────────────────

RISKS = ("low", "medium", "high", "critical")  # critical: LEKA-404
EFFECTS = ("deny", "allow")


@dataclass(frozen=True)
class Rule:
    """A policy of the workspace, as it is evaluated."""

    id: str
    name: str
    effect: str  # deny, allow
    # Permissions or actions (agent:run, workflow:run); "*" every one.
    actions: frozenset[str]
    # member, admin, owner, or a role of the workspace's own (its key);
    # none: everyone.
    roles: frozenset[str] = frozenset()
    # Conditions on the resource; a rule with any applies only to a resource
    # that meets them all.
    resource_types: frozenset[str] = frozenset()
    risk_at_least: str | None = None
    kinds: frozenset[str] = frozenset()
    categories: frozenset[str] = frozenset()
    priority: int = 0

    @property
    def conditional(self) -> bool:
        return bool(self.resource_types or self.risk_at_least or self.kinds or self.categories)


@dataclass(frozen=True)
class Subject:
    """Who asks: as the policy reads them."""

    user_id: uuid.UUID
    role: Role
    workspace_status: WorkspaceStatus = WorkspaceStatus.ACTIVE
    custom_role: str | None = None
    granted: frozenset[Permission] | None = None
    policies: tuple[Rule, ...] = ()

    @classmethod
    def of(cls, principal: Principal) -> Subject:
        return cls(
            principal.user_id,
            principal.role,
            principal.workspace_status,
            principal.custom_role,
            principal.granted,
            tuple(principal.policies),
        )

    @property
    def permissions(self) -> frozenset[Permission]:
        return self.granted if self.granted is not None else ROLE_PERMISSIONS[self.role]


@dataclass(frozen=True)
class Resource:
    """What it is asked on."""

    type: str  # entity, intention, context, capability, agent_run, workflow_run…
    id: str | None = None
    # Who it belongs to, when that changes who may act on it.
    owner_id: uuid.UUID | None = None
    # An entity an admin restricted (LEKA-402).
    restricted: bool = False
    # What policies read of it (LEKA-403): a capability's risk, kind,
    # category.
    attributes: Mapping[str, str] = field(default_factory=dict)


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
    # The policy that decided, when one did (LEKA-403).
    policy: str | None = None


def _refused(
    rule: str, reason: str, permission: Permission, message: str, policy: str | None = None
) -> Decision:
    return Decision(False, rule, reason, permission, message, policy)


def _meets(rule: Rule, resource: Resource | None) -> bool:
    if not rule.conditional:
        return True
    if resource is None:
        return False
    if rule.resource_types and resource.type not in rule.resource_types:
        return False
    said = resource.attributes
    if rule.risk_at_least is not None:
        risk = said.get("risk")
        if risk not in RISKS or RISKS.index(risk) < RISKS.index(rule.risk_at_least):
            return False
    if rule.kinds and said.get("kind") not in rule.kinds:
        return False
    return not (rule.categories and said.get("category") not in rule.categories)


def applying(
    rules: Iterable[Rule],
    subject: Subject,
    action: str,
    permission: Permission,
    resource: Resource | None,
) -> list[Rule]:
    """The rules that apply here, the one that decides first: the highest
    priority, a refusal before an exception, then by id — always the same
    order."""
    who = {subject.role.value} | ({subject.custom_role} if subject.custom_role else set())
    found = [
        r
        for r in rules
        if ({"*", action, permission.value} & r.actions)
        and (not r.roles or r.roles & who)
        and _meets(r, resource)
    ]
    found.sort(key=lambda r: (-r.priority, r.effect != "deny", r.id))
    return found


def evaluate(
    subject: Subject,
    permission: Permission,
    resource: Resource | None = None,
    *,
    anyones: Permission | None = None,
    action: str | None = None,
) -> Decision:
    """Whether `subject` may use `permission` — on `resource` when given —
    and why. `anyones`: the permission that lets one act on what someone
    else owns (intention:approve for another's run, context:manage for
    another's context). `action`: what is done under the permission, as
    policies name it (agent:run)."""
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
            f"Your role in this workspace ({subject.custom_role or subject.role.value}) "
            f"does not allow {permission.value}.",
        )
    reason = "role_grants"
    decided_by: str | None = None
    rules = applying(subject.policies, subject, action or permission.value, permission, resource)
    if rules:
        first = rules[0]
        if first.effect == "deny":
            return _refused(
                "policy",
                "policy_denied",
                permission,
                f"The workspace's policy « {first.name} » does not allow it.",
                first.id,
            )
        reason, decided_by = "policy_allows", first.id
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
    rule = {"role_grants": "role", "policy_allows": "policy"}.get(reason, reason)
    return Decision(True, rule, reason, permission, policy=decided_by)


def rules_checked(rules: Sequence[Rule]) -> Sequence[Rule]:
    """Rules as they can be: a known effect, a known risk, a priority from
    0 to 100, an action at least."""
    for r in rules:
        if r.effect not in EFFECTS:
            msg = f"{r.name}: an effect is deny or allow"
            raise RoleError(msg)
        if r.risk_at_least is not None and r.risk_at_least not in RISKS:
            msg = f"{r.name}: a risk is low, medium, high or critical"
            raise RoleError(msg)
        if not 0 <= r.priority <= 100:
            msg = f"{r.name}: a priority from 0 to 100"
            raise RoleError(msg)
        if not r.actions:
            msg = f"{r.name}: a policy names what it is about"
            raise RoleError(msg)
    return rules


def sees_restricted(role: Role) -> bool:
    """Whether a role sees restricted entities — the rest never do."""
    return Permission.ENTITY_READ_RESTRICTED in ROLE_PERMISSIONS[role]
