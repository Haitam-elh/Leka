"""Platform primitives: tenancy, the identity seam, events, secrets, storage.

Tenancy lives here — workspaces, memberships, invitations — because it is
what every other module is scoped by. What a role is ALLOWED to do is
authorisation policy and belongs to leka.governance, which imports this.

Depends on leka.core and leka.db only.
"""

from leka.platform.health import check_backing_services
from leka.platform.models import (
    Invitation,
    InvitationStatus,
    Membership,
    Role,
    Workspace,
    WorkspaceStatus,
)
from leka.platform.repository import (
    InvitationRepository,
    MembershipRepository,
    MembershipResolver,
    WorkspaceRepository,
)
from leka.platform.schemas import (
    CurrentWorkspace,
    DeletionScheduled,
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    MemberRead,
    MemberRoleUpdate,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceSummary,
    WorkspaceUpdate,
)
from leka.platform.seam import (
    CurrentUserProvider,
    SeamNotImplementedError,
    SessionStore,
    UserId,
    WorkspaceId,
    get_current_user_id,
    get_session_store,
)
from leka.platform.secrets import DecryptionError, SecretBox, secret_box
from leka.platform.service import (
    DELETION_GRACE_PERIOD,
    INVITATION_LIFETIME,
    InvitationAcceptance,
    MembershipService,
    TenancyError,
    WorkspaceService,
    hash_token,
    slugify,
)

__all__ = [
    "DELETION_GRACE_PERIOD",
    "INVITATION_LIFETIME",
    "CurrentUserProvider",
    "CurrentWorkspace",
    "DecryptionError",
    "DeletionScheduled",
    "Invitation",
    "InvitationAcceptance",
    "InvitationCreate",
    "InvitationCreated",
    "InvitationRead",
    "InvitationRepository",
    "InvitationStatus",
    "MemberRead",
    "MemberRoleUpdate",
    "Membership",
    "MembershipRepository",
    "MembershipResolver",
    "MembershipService",
    "Role",
    "SeamNotImplementedError",
    "SecretBox",
    "SessionStore",
    "TenancyError",
    "UserId",
    "Workspace",
    "WorkspaceCreate",
    "WorkspaceId",
    "WorkspaceRead",
    "WorkspaceRepository",
    "WorkspaceService",
    "WorkspaceStatus",
    "WorkspaceSummary",
    "WorkspaceUpdate",
    "check_backing_services",
    "get_current_user_id",
    "get_session_store",
    "hash_token",
    "secret_box",
    "slugify",
]
