"""LEKA ADMIN's server side (LEKA-544): the Admin API's rules and data.

LEKA's team, apart from the customers: its own accounts and sessions
(bearer tokens, for the Android app), four roles and their permissions
checked on every route, a trail of everything done and every sensitive
read, idempotent sensitive operations, the reads every LEKA ADMIN module
needs across every customer, and an activity journal derived from the
tables that already say what happened.

Sits above every module it reads (tests/test_module_boundaries.py); only
the API imports it. docs/admin/api.md is the contract.
"""

from leka.admin.access import ROLE_PERMISSIONS, AdminPermission, AdminRole, allows, permissions_of
from leka.admin.audit import apart as audit_apart
from leka.admin.audit import record as audit_record
from leka.admin.dependencies import AdminPrincipalDep, client_ip, get_admin, require_admin, route_of
from leka.admin.models import (
    ActivityEvent,
    ActivityWatermark,
    AdminAccount,
    AdminAuditEvent,
    AdminIdempotencyKey,
    AdminSession,
)
from leka.admin.schemas import AdminMe, AdminPrincipal, AdminSignedIn, AdminSignIn
from leka.admin.service import (
    AdminAccountError,
    AdminAuth,
    AdminAuthError,
    IdempotencyConflictError,
    create_account,
    once,
)

__all__ = [
    "ROLE_PERMISSIONS",
    "ActivityEvent",
    "ActivityWatermark",
    "AdminAccount",
    "AdminAccountError",
    "AdminAuditEvent",
    "AdminAuth",
    "AdminAuthError",
    "AdminIdempotencyKey",
    "AdminMe",
    "AdminPermission",
    "AdminPrincipal",
    "AdminPrincipalDep",
    "AdminRole",
    "AdminSession",
    "AdminSignIn",
    "AdminSignedIn",
    "IdempotencyConflictError",
    "allows",
    "audit_apart",
    "audit_record",
    "client_ip",
    "create_account",
    "get_admin",
    "once",
    "permissions_of",
    "require_admin",
    "route_of",
]
