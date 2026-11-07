"""Who in LEKA's team may do what in LEKA ADMIN (LEKA-544, LEKA-545).

Four roles, the backlog's. A role is a set of permissions, and a route asks
for a permission, never a role: the day a role changes, no route does.
Refused unless granted: a permission missing from a role's set is refused,
and so is a role nobody knows.

What each role grants is kept in the database (`admin_role_permissions`),
the Super Admin's to change (LEKA-545); ROLE_PERMISSIONS below is where it
starts. Two limits nobody can lift: a Super Admin may do everything, and
only a Super Admin manages the admins or reads their trail — a role able to
grant itself `admins:manage` would be a Super Admin by another name.

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
    # Suspend and reactivate an organisation; change its name, country and
    # size, as LEKA's team keeps them (LEKA-549).
    ORGANISATIONS_WRITE = "organisations:write"
    # Write an internal note about an organisation (LEKA-549): LEKA's team's
    # alone, never shown to the customer.
    ORGANISATIONS_NOTES = "organisations:notes"
    USERS_READ = "users:read"
    # Write an internal note about a person (LEKA-550), as about an organisation.
    USERS_NOTES = "users:notes"
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
    # Incidents and the team's notifications (LEKA-556); dealing with one:
    # taking it, resolving or closing it, assigning it, a note.
    INCIDENTS_READ = "incidents:read"
    INCIDENTS_WRITE = "incidents:write"
    # A list taken away as a CSV file, as filtered (LEKA-557): on top of
    # reading that list, and each one kept in the admin trail.
    EXPORTS_CREATE = "exports:create"
    AUDIT_READ = "audit:read"
    # The admins, their roles (LEKA-545).
    ADMINS_MANAGE = "admins:manage"


P = AdminPermission

Level = str  # "read", "write" or "sensitive"

# Each permission's module and what kind of action it is (LEKA-545): reading,
# writing, or a sensitive operation (what a customer wrote, money, an
# organisation's access, the admins themselves).
PERMISSION_INFO: dict[AdminPermission, tuple[str, Level]] = {
    P.DASHBOARD_READ: ("dashboard", "read"),
    P.ORGANISATIONS_READ: ("organisations", "read"),
    P.ORGANISATIONS_WRITE: ("organisations", "sensitive"),
    P.ORGANISATIONS_NOTES: ("organisations", "write"),
    P.USERS_READ: ("users", "read"),
    P.USERS_NOTES: ("users", "write"),
    P.INTENTIONS_READ: ("intentions", "read"),
    P.INTENTIONS_CONTENT: ("intentions", "sensitive"),
    P.AGENTS_READ: ("agents", "read"),
    P.CREDITS_READ: ("credits", "read"),
    P.CREDITS_WRITE: ("credits", "sensitive"),
    P.BILLING_READ: ("billing", "read"),
    P.ENVIRONMENTS_READ: ("environments", "read"),
    P.ACTIVITY_READ: ("activity", "read"),
    P.INCIDENTS_READ: ("incidents", "read"),
    P.INCIDENTS_WRITE: ("incidents", "write"),
    P.EXPORTS_CREATE: ("exports", "sensitive"),
    P.AUDIT_READ: ("audit", "sensitive"),
    P.ADMINS_MANAGE: ("admins", "sensitive"),
}

# A Super Admin's alone, whatever the roles say.
SUPER_ADMIN_ONLY = frozenset({P.ADMINS_MANAGE, P.AUDIT_READ})
GRANTABLE = frozenset(AdminPermission) - SUPER_ADMIN_ONLY

_COMMON = frozenset(
    {
        P.DASHBOARD_READ,
        P.ORGANISATIONS_READ,
        P.ORGANISATIONS_NOTES,
        P.USERS_READ,
        P.USERS_NOTES,
        P.ACTIVITY_READ,
        P.INCIDENTS_READ,
    }
)

ROLE_PERMISSIONS: dict[AdminRole, frozenset[AdminPermission]] = {
    AdminRole.SUPER_ADMIN: frozenset(AdminPermission),
    AdminRole.OPERATIONS: _COMMON
    | {
        P.ORGANISATIONS_WRITE,
        P.INTENTIONS_READ,
        P.AGENTS_READ,
        P.CREDITS_READ,
        P.ENVIRONMENTS_READ,
        P.INCIDENTS_WRITE,
        P.EXPORTS_CREATE,
    },
    AdminRole.SUPPORT: _COMMON
    | {
        P.INTENTIONS_READ,
        P.INTENTIONS_CONTENT,
        P.AGENTS_READ,
        P.CREDITS_READ,
        P.ENVIRONMENTS_READ,
        P.INCIDENTS_WRITE,
    },
    AdminRole.FINANCE: _COMMON
    | {P.AGENTS_READ, P.CREDITS_READ, P.CREDITS_WRITE, P.BILLING_READ, P.EXPORTS_CREATE},
}


def permissions_of(role: str) -> frozenset[AdminPermission]:
    """What a role grants to start with. A role this file does not know
    grants nothing."""
    try:
        return ROLE_PERMISSIONS[AdminRole(role)]
    except ValueError:
        return frozenset()


def allows(role: str, permission: AdminPermission) -> bool:
    return permission in permissions_of(role)


def granted(role: str, stored: frozenset[str]) -> frozenset[AdminPermission]:
    """What a role grants now: everything for a Super Admin; for any other,
    what the Super Admin left it (`stored`), never a Super Admin's own."""
    try:
        known = AdminRole(role)
    except ValueError:
        return frozenset()
    if known is AdminRole.SUPER_ADMIN:
        return frozenset(AdminPermission)
    return frozenset(p for p in AdminPermission if p.value in stored) & GRANTABLE
