"""Governance: authorisation and audit.

Tenancy — workspaces, memberships, roles — is leka.platform. What a role is
ALLOWED to do is here, together with the FastAPI dependencies that enforce
it and the audit trail that records it.

Depends on leka.platform and, through the seam, on LEKA-330's notion of the
current user. Consumed by leka.api.
"""

from leka.governance.dependencies import (
    PrincipalDep,
    get_current_principal,
    get_governance_service,
    require_permission,
    require_role,
)
from leka.governance.repository import AuditRepository
from leka.governance.schemas import (
    ROLE_PERMISSIONS,
    ROLE_RANK,
    WRITE_PERMISSIONS,
    Permission,
    Principal,
)
from leka.governance.service import (
    AuthorisationError,
    GovernanceService,
    WorkspaceSuspendedError,
    WorkspaceUnavailableError,
    check_lifecycle,
    check_permission,
    check_role,
)

__all__ = [
    "ROLE_PERMISSIONS",
    "ROLE_RANK",
    "WRITE_PERMISSIONS",
    "AuditRepository",
    "AuthorisationError",
    "GovernanceService",
    "Permission",
    "Principal",
    "PrincipalDep",
    "WorkspaceSuspendedError",
    "WorkspaceUnavailableError",
    "check_lifecycle",
    "check_permission",
    "check_role",
    "get_current_principal",
    "get_governance_service",
    "require_permission",
    "require_role",
]
