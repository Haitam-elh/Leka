"""Who in LEKA's team may do what in LEKA ADMIN (LEKA-544, LEKA-545).

Four roles, the backlog's. A role is a set of permissions, and a route asks
for a permission, never a role: the day a role changes, no route does.
Refused unless granted: a permission missing from a role's set is refused,
and so is a role nobody knows.

The permissions are per module and per action — read, write, and the
sensitive reads (what a customer wrote, what an agent delivered for them),
which are kept apart so a role can see that an intention exists without
reading it.

  role          what it is for
  super_admin   everything, the admins themselves included
  operations    the platform running: organisations (suspend, reactivate),
                integrations, runs, monitoring
  support       helping a customer: their organisation, their people, their
                intentions as they wrote them
  finance       the money: subscriptions, Stripe, credits (adding them, with
                a reason)
"""

from __future__ import annotations

import enum


class AdminRole(enum.StrEnum):
    SUPER_ADMIN = "super_admin"
    OPERATIONS = "operations"
    SUPPORT = "support"
    FINANCE = "finance"


class AdminPermission(enum.StrEnum):
    DASHBOARD_READ = "dashboard:read"
    ORGANISATIONS_READ = "organisations:read"
    # Suspend and reactivate an organisation.
    ORGANISATIONS_WRITE = "organisations:write"
    USERS_READ = "users:read"
    INTENTIONS_READ = "intentions:read"
    # What a customer asked, in their words, and what agents delivered.
    INTENTIONS_CONTENT = "intentions:content"
    AGENTS_READ = "agents:read"
    CREDITS_READ = "credits:read"
    # Credits added to an organisation's month, with a reason.
    CREDITS_WRITE = "credits:write"
    BILLING_READ = "billing:read"
    ENVIRONMENTS_READ = "environments:read"
    ACTIVITY_READ = "activity:read"
    AUDIT_READ = "audit:read"
    # The admins, their roles (LEKA-545).
    ADMINS_MANAGE = "admins:manage"


P = AdminPermission

_COMMON = frozenset({P.DASHBOARD_READ, P.ORGANISATIONS_READ, P.USERS_READ, P.ACTIVITY_READ})

ROLE_PERMISSIONS: dict[AdminRole, frozenset[AdminPermission]] = {
    AdminRole.SUPER_ADMIN: frozenset(AdminPermission),
    AdminRole.OPERATIONS: _COMMON
    | {
        P.ORGANISATIONS_WRITE,
        P.INTENTIONS_READ,
        P.AGENTS_READ,
        P.CREDITS_READ,
        P.ENVIRONMENTS_READ,
    },
    AdminRole.SUPPORT: _COMMON
    | {
        P.INTENTIONS_READ,
        P.INTENTIONS_CONTENT,
        P.AGENTS_READ,
        P.CREDITS_READ,
        P.ENVIRONMENTS_READ,
    },
    AdminRole.FINANCE: _COMMON | {P.AGENTS_READ, P.CREDITS_READ, P.CREDITS_WRITE, P.BILLING_READ},
}


def permissions_of(role: str) -> frozenset[AdminPermission]:
    """What a role grants. A role this file does not know grants nothing."""
    try:
        return ROLE_PERMISSIONS[AdminRole(role)]
    except ValueError:
        return frozenset()


def allows(role: str, permission: AdminPermission) -> bool:
    return permission in permissions_of(role)
