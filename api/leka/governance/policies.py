"""Roles and policies of a workspace (LEKA-403): kept, changed, assigned —
every change in its history — and read on every request, with the role,
for the one evaluation that decides (policy.evaluate).

    a role of its own     a base role (member, admin), what it adds, what it
                          takes away — given to a person whose seat has that
                          base; a seat that changed base no longer carries it
    a policy              for these actions, these roles, these resources:
                          refuse, or allow by exception — at a priority
    their history         created, updated, deleted, assigned, unassigned —
                          who, when, before and after; append-only
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from leka.governance.models import GovernanceEvent, RoleAssignment, WorkspacePolicy, WorkspaceRole
from leka.governance.policy import (
    BASES,
    CustomRole,
    RoleError,
    Rule,
    Subject,
    checked_role,
    rules_checked,
)
from leka.governance.repository import PolicyRepository
from leka.governance.schemas import Permission
from leka.platform import MembershipResolver, Role, WorkspaceStatus

# What policies name besides permissions: the executions decided before
# they run.
ACTIONS = ("agent:run", "workflow:run")
KEY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def role_of(row: WorkspaceRole) -> CustomRole:
    return CustomRole(
        key=row.key,
        name=row.name,
        base=Role(row.base),
        added=frozenset(Permission(p) for p in row.added),
        removed=frozenset(Permission(p) for p in row.removed),
    )


def rule_of(row: WorkspacePolicy) -> Rule:
    said = row.conditions or {}

    def words(key: str) -> frozenset[str]:
        value = said.get(key)
        return frozenset(str(v) for v in value) if isinstance(value, list) else frozenset()

    risk = said.get("risk_at_least")
    return Rule(
        id=str(row.id),
        name=row.name,
        effect=row.effect,
        actions=frozenset(row.actions),
        roles=frozenset(row.roles),
        resource_types=words("resource_types"),
        risk_at_least=str(risk) if risk else None,
        kinds=words("kinds"),
        categories=words("categories"),
        priority=row.priority,
    )


@dataclass(frozen=True)
class Standing:
    """What a person holds here beyond their seat: a role of the
    workspace's own, what it grants, the policies in force."""

    custom_role: str | None
    granted: frozenset[Permission] | None
    policies: tuple[Rule, ...]


async def standing(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, role: Role
) -> Standing:
    """Read on every request, like the seat: a role taken away, a policy
    changed — in force at the next one."""
    repo = PolicyRepository(session, workspace_id)
    held = await repo.held_role(user_id)
    policies = tuple(rule_of(p) for p in await repo.policies(enabled_only=True))
    if held is None or held.base != role.value:
        return Standing(None, None, policies)
    custom = role_of(held)
    return Standing(custom.key, custom.permissions, policies)


async def subject_of(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID | None
) -> Subject | None:
    """A person, as the evaluation reads them now — for work done on their
    behalf. None: no longer in the workspace."""
    if user_id is None:
        return None
    seat = await MembershipResolver(session).get_for_user_in_workspace(user_id, workspace_id)
    if seat is None:
        return None
    held = await standing(session, workspace_id, user_id, seat.role)
    return Subject(
        user_id,
        seat.role,
        WorkspaceStatus.ACTIVE,
        held.custom_role,
        held.granted,
        held.policies,
    )


def _said_role(row: WorkspaceRole) -> dict[str, object]:
    return {
        "key": row.key,
        "name": row.name,
        "description": row.description,
        "base": row.base,
        "added": sorted(row.added),
        "removed": sorted(row.removed),
    }


def _said_policy(row: WorkspacePolicy) -> dict[str, object]:
    return {
        "name": row.name,
        "description": row.description,
        "effect": row.effect,
        "actions": sorted(row.actions),
        "roles": sorted(row.roles),
        "conditions": dict(row.conditions or {}),
        "priority": row.priority,
        "enabled": row.enabled,
    }


@dataclass(frozen=True)
class PolicyInput:
    name: str
    effect: str
    actions: Sequence[str]
    roles: Sequence[str] = ()
    resource_types: Sequence[str] = ()
    risk_at_least: str | None = None
    kinds: Sequence[str] = ()
    categories: Sequence[str] = ()
    priority: int = 50
    enabled: bool = True
    description: str | None = None

    def conditions(self) -> dict[str, object]:
        said: dict[str, object] = {}
        for key in ("resource_types", "kinds", "categories"):
            value = list(dict.fromkeys(getattr(self, key)))
            if value:
                said[key] = value
        if self.risk_at_least:
            said["risk_at_least"] = self.risk_at_least
        return said


class PolicyService:
    """A workspace's roles of its own and its policies — every change kept."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._repo = PolicyRepository(session, workspace_id)

    def _event(
        self,
        subject_type: str,
        subject_id: str,
        kind: str,
        by: uuid.UUID | None,
        before: Mapping[str, object] | None = None,
        after: Mapping[str, object] | None = None,
    ) -> None:
        self._repo.add(
            GovernanceEvent(
                workspace_id=self._workspace_id,
                id=uuid.uuid4(),
                subject_type=subject_type,
                subject_id=subject_id[:100],
                kind=kind,
                by=by,
                at=datetime.now(UTC),
                before=dict(before) if before is not None else None,
                after=dict(after) if after is not None else None,
            )
        )

    # ── roles ───────────────────────────────────────────────────────────────

    async def roles(self) -> list[tuple[WorkspaceRole, int]]:
        held: dict[uuid.UUID, int] = {}
        for a in await self._repo.assignments():
            held[a.role_id] = held.get(a.role_id, 0) + 1
        return [(r, held.get(r.id, 0)) for r in await self._repo.roles()]

    async def holders(self) -> dict[uuid.UUID, str]:
        """Who holds which role of the workspace's own: user → key."""
        keys = {r.id: r.key for r in await self._repo.roles()}
        return {
            a.user_id: keys[a.role_id] for a in await self._repo.assignments() if a.role_id in keys
        }

    async def save_role(
        self,
        key: str,
        *,
        name: str,
        base: str,
        added: Sequence[str],
        removed: Sequence[str],
        description: str | None,
        by: uuid.UUID,
    ) -> WorkspaceRole:
        """Created, or changed — RoleError when it cannot be."""
        if not key or set(key) - KEY_CHARS or key in {r.value for r in Role}:
            msg = "a role's key is kebab-case, and not member, admin or owner"
            raise RoleError(msg)
        try:
            role = CustomRole(
                key,
                name,
                Role(base),
                frozenset(Permission(p) for p in added),
                frozenset(Permission(p) for p in removed),
            )
        except ValueError as error:
            msg = "an unknown base role or permission"
            raise RoleError(msg) from error
        if role.base not in BASES:
            msg = "a role is built on the member's or the admin's"
            raise RoleError(msg)
        checked_role(role)
        row = await self._repo.role(key)
        if (
            row is not None
            and row.base != base
            and any(a.role_id == row.id for a in await self._repo.assignments())
        ):
            msg = "its base cannot change while people hold it"
            raise RoleError(msg)
        before = _said_role(row) if row is not None else None
        if row is None:
            row = WorkspaceRole(
                workspace_id=self._workspace_id, id=uuid.uuid4(), key=key, created_by=by
            )
            self._repo.add(row)
        row.name = name
        row.description = description
        row.base = base
        row.added = sorted(p.value for p in role.added)
        row.removed = sorted(p.value for p in role.removed)
        self._event("role", key, "updated" if before else "created", by, before, _said_role(row))
        await self._session.flush()
        return row

    async def delete_role(self, key: str, *, by: uuid.UUID) -> bool:
        row = await self._repo.role(key)
        if row is None:
            return False
        if any(a.role_id == row.id for a in await self._repo.assignments()):
            msg = "people hold it: give them another role first"
            raise RoleError(msg)
        self._event("role", key, "deleted", by, _said_role(row), None)
        await self._repo.remove(row)
        await self._session.flush()
        return True

    async def assign(
        self, user_id: uuid.UUID, key: str | None, *, seat: Role, by: uuid.UUID
    ) -> None:
        """Given — on the base its seat has — or taken back (None)."""
        current = await self._repo.assignment(user_id)
        if key is None:
            if current is not None:
                await self._repo.remove(current)
                self._event(
                    "assignment", str(user_id), "unassigned", by, {"role_id": str(current.role_id)}
                )
                await self._session.flush()
            return
        row = await self._repo.role(key)
        if row is None:
            msg = f"no role {key!r}"
            raise RoleError(msg)
        if row.base != seat.value:
            msg = f"their seat is {seat.value}; {row.name} is built on {row.base}"
            raise RoleError(msg)
        if current is None:
            current = RoleAssignment(
                workspace_id=self._workspace_id, id=uuid.uuid4(), user_id=user_id, role_id=row.id
            )
            self._repo.add(current)
        current.role_id = row.id
        current.assigned_by = by
        self._event("assignment", str(user_id), "assigned", by, None, {"role": key})
        await self._session.flush()

    # ── policies ────────────────────────────────────────────────────────────

    async def policies(self) -> Sequence[WorkspacePolicy]:
        return await self._repo.policies()

    async def _checked(self, said: PolicyInput) -> None:
        known = {p.value for p in Permission} | set(ACTIONS) | {"*"}
        unknown = set(said.actions) - known
        if unknown:
            msg = f"unknown action {sorted(unknown)}"
            raise RoleError(msg)
        roles = {r.value for r in Role} | {r.key for r in await self._repo.roles()}
        if set(said.roles) - roles:
            msg = f"unknown role {sorted(set(said.roles) - roles)}"
            raise RoleError(msg)
        rules_checked(
            [
                Rule(
                    "new",
                    said.name,
                    said.effect,
                    frozenset(said.actions),
                    risk_at_least=said.risk_at_least,
                    priority=said.priority,
                )
            ]
        )

    async def save_policy(
        self, said: PolicyInput, *, by: uuid.UUID, policy_id: uuid.UUID | None = None
    ) -> WorkspacePolicy | None:
        """Created, or changed — None for a policy this workspace does not
        have; RoleError when it cannot be."""
        await self._checked(said)
        row = await self._repo.policy(policy_id) if policy_id is not None else None
        if policy_id is not None and row is None:
            return None
        before = _said_policy(row) if row is not None else None
        if row is None:
            row = WorkspacePolicy(workspace_id=self._workspace_id, id=uuid.uuid4(), created_by=by)
            self._repo.add(row)
        row.name = said.name
        row.description = said.description
        row.effect = said.effect
        row.actions = list(dict.fromkeys(said.actions))
        row.roles = list(dict.fromkeys(said.roles))
        row.conditions = said.conditions()
        row.priority = said.priority
        row.enabled = said.enabled
        await self._session.flush()
        self._event(
            "policy", str(row.id), "updated" if before else "created", by, before, _said_policy(row)
        )
        await self._session.flush()
        # What the database set (its updated_at), read back now.
        await self._session.refresh(row)
        return row

    async def delete_policy(self, policy_id: uuid.UUID, *, by: uuid.UUID) -> bool:
        row = await self._repo.policy(policy_id)
        if row is None:
            return False
        self._event("policy", str(row.id), "deleted", by, _said_policy(row), None)
        await self._repo.remove(row)
        await self._session.flush()
        return True

    async def history(
        self, *, subject_type: str | None = None, limit: int = 100
    ) -> Sequence[GovernanceEvent]:
        return await self._repo.history(subject_type=subject_type, limit=limit)

    async def rules(self) -> tuple[Rule, ...]:
        return tuple(rule_of(p) for p in await self._repo.policies(enabled_only=True))

    async def custom(self, key: str) -> CustomRole | None:
        row = await self._repo.role(key)
        return role_of(row) if row is not None else None
