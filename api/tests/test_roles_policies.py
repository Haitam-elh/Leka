"""Roles and policies (LEKA-403), pure — inheritance, precedence, and how
conflicting policies are decided, always the same way.

What these protect: a role of the workspace's own inherits its base's
permissions, adds, and takes away — taking away wins; it never grants what
only an owner may, never takes away reading the workspace, never adds what
its base has nor takes away what it has not. A policy refuses only what it
names, to whom it names, on the resources it names — a conditional one
never applies without a resource; the highest priority decides; at the same
priority a refusal wins; an exception lifts a lower refusal but never grants
what the role does not carry; the order is the same every time.
"""

from __future__ import annotations

import uuid

import pytest

from leka.governance import (
    CustomRole,
    Permission,
    Resource,
    RoleError,
    Rule,
    Subject,
    evaluate,
)
from leka.governance.policy import applying, checked_role
from leka.platform import Role, WorkspaceStatus

ME = uuid.uuid4()
RISKY = Resource("capability", "build-fixer", attributes={"risk": "high", "kind": "agent"})
TAME = Resource("capability", "debug-assistant", attributes={"risk": "low", "kind": "agent"})


def who(role: Role = Role.MEMBER, custom: CustomRole | None = None, *rules: Rule) -> Subject:
    return Subject(
        ME,
        role,
        WorkspaceStatus.ACTIVE,
        custom.key if custom else None,
        custom.permissions if custom else None,
        rules,
    )


def deny(name: str, priority: int = 50, **more: object) -> Rule:
    return Rule(name, name, "deny", frozenset({"agent:run"}), priority=priority, **more)  # type: ignore[arg-type]


def allow(name: str, priority: int = 50, **more: object) -> Rule:
    return Rule(name, name, "allow", frozenset({"agent:run"}), priority=priority, **more)  # type: ignore[arg-type]


# ── roles of the workspace's own ───────────────────────────────────────────


def test_a_role_inherits_adds_and_takes_away_taking_away_wins() -> None:
    lead = CustomRole(
        "tech-lead",
        "Tech Lead",
        Role.MEMBER,
        added=frozenset({Permission.INTENTION_APPROVE, Permission.JOB_READ}),
        removed=frozenset({Permission.SOURCE_READ}),
    )
    checked_role(lead)
    granted = lead.permissions
    assert Permission.INTENTION_CREATE in granted  # inherited
    assert Permission.INTENTION_APPROVE in granted  # added
    assert Permission.SOURCE_READ not in granted  # taken away
    decided = evaluate(who(Role.MEMBER, lead), Permission.INTENTION_APPROVE)
    assert decided.allowed
    refused = evaluate(who(Role.MEMBER, lead), Permission.SOURCE_READ)
    assert not refused.allowed and "tech-lead" in refused.message


@pytest.mark.parametrize(
    ("role", "said"),
    [
        (CustomRole("x", "X", Role.OWNER), "member's or the admin's"),
        (
            CustomRole("x", "X", Role.ADMIN, added=frozenset({Permission.WORKSPACE_DELETE})),
            "only an owner",
        ),
        (
            CustomRole("x", "X", Role.MEMBER, added=frozenset({Permission.INTENTION_CREATE})),
            "already grants",
        ),
        (
            CustomRole("x", "X", Role.MEMBER, removed=frozenset({Permission.SOURCE_MANAGE})),
            "does not grant",
        ),
        (
            CustomRole("x", "X", Role.MEMBER, removed=frozenset({Permission.WORKSPACE_READ})),
            "reads the workspace",
        ),
    ],
)
def test_a_role_that_cannot_be_is_refused(role: CustomRole, said: str) -> None:
    with pytest.raises(RoleError, match=said):
        checked_role(role)


# ── policies ───────────────────────────────────────────────────────────────


def test_a_policy_refuses_only_what_whom_and_where_it_names() -> None:
    risky = deny(
        "no-risky-agents", risk_at_least="medium", resource_types=frozenset({"capability"})
    )
    member = who(Role.MEMBER, None, risky)
    refused = evaluate(member, Permission.INTENTION_CREATE, RISKY, action="agent:run")
    assert (refused.allowed, refused.rule, refused.reason, refused.policy) == (
        False,
        "policy",
        "policy_denied",
        "no-risky-agents",
    )
    assert "no-risky-agents" in refused.message
    # Below its risk; another action; no resource at all: not its business.
    assert evaluate(member, Permission.INTENTION_CREATE, TAME, action="agent:run").allowed
    assert evaluate(member, Permission.INTENTION_CREATE, RISKY, action="workflow:run").allowed
    assert evaluate(member, Permission.INTENTION_CREATE, action="agent:run").allowed
    # Only to whom it names.
    admins_only = deny("admins-no", roles=frozenset({"admin"}))
    assert evaluate(
        who(Role.MEMBER, None, admins_only), Permission.INTENTION_CREATE, action="agent:run"
    ).allowed
    assert not evaluate(
        who(Role.ADMIN, None, admins_only), Permission.INTENTION_CREATE, action="agent:run"
    ).allowed


def test_conflicts_the_highest_priority_decides_a_refusal_wins_a_tie() -> None:
    no = deny("no", priority=50)
    exception = allow("leads-may", priority=60, roles=frozenset({"tech-lead"}))
    lead = CustomRole("tech-lead", "Tech Lead", Role.MEMBER)
    as_lead = who(Role.MEMBER, lead, no, exception)
    decided = evaluate(as_lead, Permission.INTENTION_CREATE, action="agent:run")
    assert (decided.allowed, decided.reason, decided.policy) == (True, "policy_allows", "leads-may")
    # The exception is not theirs: the refusal stands.
    assert not evaluate(
        who(Role.MEMBER, None, no, exception), Permission.INTENTION_CREATE, action="agent:run"
    ).allowed
    # Same priority: refusing wins, whatever the order they come in.
    tie = allow("leads-may", priority=50, roles=frozenset({"tech-lead"}))
    for rules in ((no, tie), (tie, no)):
        assert not evaluate(
            who(Role.MEMBER, lead, *rules), Permission.INTENTION_CREATE, action="agent:run"
        ).allowed
    # Same everything: by id.
    a, b = deny("a"), deny("b")
    assert [
        r.id for r in applying((b, a), who(), "agent:run", Permission.INTENTION_CREATE, None)
    ] == [
        "a",
        "b",
    ]


def test_an_exception_never_grants_what_the_role_does_not_carry() -> None:
    generous = Rule(
        "everyone-approves", "everyone-approves", "allow", frozenset({"*"}), priority=100
    )
    decided = evaluate(who(Role.MEMBER, None, generous), Permission.INTENTION_APPROVE)
    assert (decided.allowed, decided.rule) == (False, "role")
