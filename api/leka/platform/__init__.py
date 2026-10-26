"""Platform primitives: tenancy, the identity seam, events, secrets, storage.

Tenancy lives here — workspaces, memberships, invitations — because it is
what every other module is scoped by. What a role is ALLOWED to do is
authorisation policy and belongs to leka.governance, which imports this.

Depends on leka.core and leka.db only.
"""

from leka.platform.branding import MAX_LOGO_BYTES, LogoRefusedError, drop_logo, keep_logo, logo_of
from leka.platform.health import check_backing_services
from leka.platform.models import (
    Invitation,
    InvitationStatus,
    Membership,
    Role,
    Workspace,
    WorkspaceStatus,
)
from leka.platform.posture import Posture, database_tls
from leka.platform.posture import posture as platform_posture
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
    AccountClosure,
    InvitationAcceptance,
    LastOwnerError,
    MembershipService,
    TenancyError,
    WorkspaceService,
    hash_token,
    slugify,
)
from leka.platform.storage import (
    LocalObjectStore,
    ObjectNotFoundError,
    ObjectStore,
    ObjectStoreError,
    S3ObjectStore,
    StoredObject,
    build_object_store,
    from_bytes,
    object_key,
    object_store,
    reset_object_store,
    workspace_prefix,
)

__all__ = [
    "DELETION_GRACE_PERIOD",
    "INVITATION_LIFETIME",
    "MAX_LOGO_BYTES",
    "AccountClosure",
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
    "LastOwnerError",
    "LocalObjectStore",
    "LogoRefusedError",
    "MemberRead",
    "MemberRoleUpdate",
    "Membership",
    "MembershipRepository",
    "MembershipResolver",
    "MembershipService",
    "ObjectNotFoundError",
    "ObjectStore",
    "ObjectStoreError",
    "Posture",
    "Role",
    "S3ObjectStore",
    "SeamNotImplementedError",
    "SecretBox",
    "SessionStore",
    "StoredObject",
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
    "build_object_store",
    "check_backing_services",
    "database_tls",
    "drop_logo",
    "from_bytes",
    "get_current_user_id",
    "get_session_store",
    "hash_token",
    "keep_logo",
    "logo_of",
    "object_key",
    "object_store",
    "platform_posture",
    "reset_object_store",
    "secret_box",
    "slugify",
    "workspace_prefix",
]
