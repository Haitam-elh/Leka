"""The authorisation model (LEKA-402), pure: one function decides, in one
order, and says why.

What these protect: a workspace awaiting deletion refuses everything, a
suspended one every write and no read — before the role is even looked at;
a role decides by the matrix; what someone else owns takes the permission
that reaches anyone's, one's own does not; a restricted entity is refused to
a role that may not read restricted entities, seen by one that may; every
decision says its rule and its reason, the same everywhere.
"""

from __future__ import annotations

import uuid

import pytest

from leka.governance import Permission, Resource, Subject, evaluate, sees_restricted
from leka.platform import Role, WorkspaceStatus

ME = uuid.uuid4()
SOMEONE = uuid.uuid4()


def who(role: Role, status: WorkspaceStatus = WorkspaceStatus.ACTIVE) -> Subject:
    return Subject(ME, role, status)


def said(decision: object) -> tuple[bool, str, str]:
    return (decision.allowed, decision.rule, decision.reason)  # type: ignore[attr-defined]


def test_the_workspace_decides_first() -> None:
    gone = who(Role.OWNER, WorkspaceStatus.PENDING_DELETION)
    assert said(evaluate(gone, Permission.WORKSPACE_READ)) == (
        False,
        "workspace",
        "workspace_unavailable",
    )
    suspended = who(Role.OWNER, WorkspaceStatus.SUSPENDED)
    assert said(evaluate(suspended, Permission.WORKSPACE_UPDATE)) == (
        False,
        "workspace",
        "workspace_suspended",
    )
    # A read stays a read: an unpaid invoice is not data loss.
    assert evaluate(suspended, Permission.INTENTION_READ).allowed
    # The workspace before the role: a member of a suspended workspace is
    # told it is suspended, not that their role is short.
    member = who(Role.MEMBER, WorkspaceStatus.SUSPENDED)
    assert evaluate(member, Permission.SOURCE_MANAGE).reason == "workspace_suspended"


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (Role.MEMBER, Permission.INTENTION_CREATE, True),
        (Role.MEMBER, Permission.SOURCE_MANAGE, False),
        (Role.MEMBER, Permission.ACCESS_READ, False),
        (Role.ADMIN, Permission.ENTITY_RESTRICT, True),
        (Role.ADMIN, Permission.WORKSPACE_DELETE, False),
        (Role.OWNER, Permission.WORKSPACE_DELETE, True),
    ],
)
def test_the_role_decides_by_the_matrix(role: Role, permission: Permission, allowed: bool) -> None:
    decided = evaluate(who(role), permission)
    assert decided.allowed is allowed
    assert decided.rule == "role"
    assert decided.reason == ("role_grants" if allowed else "role_lacks_permission")
    if not allowed:
        assert role.value in decided.message and permission.value in decided.message


def test_what_someone_else_owns_takes_the_permission_that_reaches_anyone_s() -> None:
    mine = Resource("agent_run", "r1", owner_id=ME)
    theirs = Resource("agent_run", "r2", owner_id=SOMEONE)
    member, admin = who(Role.MEMBER), who(Role.ADMIN)
    anyones = Permission.INTENTION_APPROVE
    assert said(evaluate(member, Permission.INTENTION_CREATE, mine, anyones=anyones)) == (
        True,
        "owner",
        "owner",
    )
    assert said(evaluate(member, Permission.INTENTION_CREATE, theirs, anyones=anyones)) == (
        False,
        "owner",
        "not_owner",
    )
    assert evaluate(admin, Permission.INTENTION_CREATE, theirs, anyones=anyones).allowed


def test_a_restricted_entity_only_for_who_may_read_restricted_entities() -> None:
    secret = Resource("entity", "e1", restricted=True)
    assert said(evaluate(who(Role.MEMBER), Permission.WORKSPACE_READ, secret)) == (
        False,
        "restriction",
        "restricted",
    )
    assert said(evaluate(who(Role.ADMIN), Permission.WORKSPACE_READ, secret)) == (
        True,
        "read_restricted",
        "read_restricted",
    )
    assert (sees_restricted(Role.MEMBER), sees_restricted(Role.ADMIN)) == (False, True)
    # Nothing restricted: nothing to refuse.
    assert evaluate(who(Role.MEMBER), Permission.WORKSPACE_READ, Resource("entity", "e2")).allowed
