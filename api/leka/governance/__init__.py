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
from leka.governance.models import AccessDecision, EntityRestriction
from leka.governance.policy import Decision, Resource, Subject, evaluate, sees_restricted
from leka.governance.repository import AuditRepository, RestrictionRepository
from leka.governance.schemas import (
    ROLE_PERMISSIONS,
    ROLE_RANK,
    WRITE_PERMISSIONS,
    AccessDecisionRead,
    AccessModelRead,
    Permission,
    Principal,
    RestrictionRead,
    RestrictionUpdate,
    RolePermissionsRead,
)
from leka.governance.service import (
    AuthorisationError,
    GovernanceService,
    RestrictionService,
    WorkspaceSuspendedError,
    WorkspaceUnavailableError,
    authorize,
    check_lifecycle,
    check_permission,
    check_role,
    hidden_for,
    hidden_on_behalf,
    record,
    record_apart,
    worth_keeping,
)
from leka.governance.team import (
    PendingInvitationRead,
    TeamMemberRead,
    inviter_name,
)
from leka.governance.team import members as team_members
from leka.governance.team import pending as pending_invitations
from leka.governance.team import revoke as revoke_invitation

__all__ = [
    "ROLE_PERMISSIONS",
    "ROLE_RANK",
    "WRITE_PERMISSIONS",
    "AccessDecision",
    "AccessDecisionRead",
    "AccessModelRead",
    "AuditRepository",
    "AuthorisationError",
    "Decision",
    "EntityRestriction",
    "GovernanceService",
    "PendingInvitationRead",
    "Permission",
    "Principal",
    "PrincipalDep",
    "Resource",
    "RestrictionRead",
    "RestrictionRepository",
    "RestrictionService",
    "RestrictionUpdate",
    "RolePermissionsRead",
    "Subject",
    "TeamMemberRead",
    "WorkspaceSuspendedError",
    "WorkspaceUnavailableError",
    "authorize",
    "check_lifecycle",
    "check_permission",
    "check_role",
    "evaluate",
    "get_current_principal",
    "get_governance_service",
    "hidden_for",
    "hidden_on_behalf",
    "inviter_name",
    "pending_invitations",
    "record",
    "record_apart",
    "require_permission",
    "require_role",
    "revoke_invitation",
    "sees_restricted",
    "team_members",
    "worth_keeping",
]
