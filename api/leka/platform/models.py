"""Platform-level tables: the tenant, who belongs to it, and who is invited.

This is tenancy — the question of WHICH organisation a row belongs to, and
who may enter it. It is not authorisation policy: what a role is allowed to
do lives in leka.governance.

Membership and Role live here rather than in governance because creating a
workspace creates its owner's membership in the same transaction, and
platform sits below governance in the dependency order. Governance imports
this; the reverse would invert the graph (architecture rule 1).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


def _values(enum_class: type[enum.StrEnum]) -> list[str]:
    """Store the enum VALUE, not the member name."""
    return [member.value for member in enum_class]


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A person. MINIMAL STUB — LEKA-330 owns this table.

    ┌────────────────────────────────────────────────────────────────────┐
    │ LEKA-330: replace this class with the real User model in           │
    │ leka/identity/models.py, and delete it from here. SQLAlchemy will  │
    │ tell you loudly if both exist ("Table 'users' is already defined")│
    │ — that error is the handover, not a problem.                       │
    └────────────────────────────────────────────────────────────────────┘

    It exists only so that the foreign keys from memberships and invitations
    resolve. Without a users table in the metadata, `alembic check` sees two
    constraints in the database with no counterpart and proposes dropping
    them on every run — which would quietly remove what stops a membership
    pointing at a deleted person.

    Four columns, exactly what migration 001 created. No password_hash, no
    session, no MFA: authentication is LEKA-330's, and adding a column here
    would be writing that ticket.

    Deliberately NOT workspace-scoped — one of the two exceptions to
    architecture rule 2. A consultant working for two customers signs in
    once; which workspaces they may enter is recorded in Membership below.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)


class Role(enum.StrEnum):
    """What a member may do in a workspace.

    Three, deliberately. The mockups show seven labels — Tech Lead, Ops,
    Security and so on — but those are job titles, not authorisation
    boundaries: they all need the same thing from LEKA.

    No `viewer`. `member` already means "read, and create intentions", and
    creating intentions is most of the product's value; a role that cannot is
    a role with almost nothing. Adding one later costs a CHECK constraint;
    removing one costs migrating every existing membership. The asymmetry
    says wait for evidence.

    See docs/permissions.md for the full matrix.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class WorkspaceStatus(enum.StrEnum):
    """Where a workspace is in its life.

    Handled in exactly one place — the dependency that resolves the request
    principal — never route by route. A status check repeated in forty routes
    is a status check missing from one of them.
    """

    ACTIVE = "active"
    # Reads allowed, writes refused. An unpaid invoice must not look like a
    # bug: the API says why, with 403 and a message, never a 404.
    SUSPENDED = "suspended"
    # No access at all, during the grace period before the data is erased.
    PENDING_DELETION = "pending_deletion"


class InvitationStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class Workspace(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One customer organisation. The tenant.

    The only table with no workspace_id: it *is* the workspace. Everything
    else references it (architecture rule 2), and everything else cascades
    from it — which is what makes "delete this customer" a single DELETE and
    a GDPR obligation we can actually meet.
    """

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    status: Mapped[WorkspaceStatus] = mapped_column(
        Enum(
            WorkspaceStatus,
            name="status",
            native_enum=False,
            length=50,
            values_callable=_values,
        ),
        nullable=False,
        server_default=WorkspaceStatus.ACTIVE.value,
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When deletion was requested. The grace period runs from here, and a
    # customer who changes their mind inside it loses nothing.
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Workspace-level configuration: retention, default environment, display
    # preferences. JSONB because this list will grow with the product, and a
    # column per setting means a migration per preference.
    settings: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class Membership(Base, WorkspaceScopedMixin):
    """A person's seat in a workspace, with a role.

    THIS is what grants access. Removing the row removes the access — and
    because the principal is resolved from here on every request rather than
    frozen into a session at sign-in, that removal takes effect immediately
    rather than at the next login.

    user_id references the users table by name rather than by imported model:
    that table belongs to LEKA-330, and platform does not import identity.
    """

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_memberships_workspace_user"),
        Index("ix_memberships_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", native_enum=False, length=50, values_callable=_values),
        nullable=False,
    )


class Invitation(Base, WorkspaceScopedMixin):
    """An offer of a seat, sent to an email address.

    The token is stored HASHED, never in the clear. An invitation token is a
    credential: whoever holds it joins a customer's workspace. A leaked
    backup must not be a set of usable invitations — the same reasoning as
    docs/adr/005-credential-storage.md, applied to a shorter-lived secret.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        # One live invitation per address per workspace. Re-inviting replaces
        # rather than accumulating, so revoking one does not leave three.
        UniqueConstraint("workspace_id", "email", name="uq_invitations_workspace_email"),
        Index("ix_invitations_token_hash", "token_hash"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", native_enum=False, length=50, values_callable=_values),
        nullable=False,
    )

    # sha256 of the token we emailed. Looked up by hash; the clear value
    # exists only in the invitee's inbox.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    status: Mapped[InvitationStatus] = mapped_column(
        Enum(
            InvitationStatus,
            name="status",
            native_enum=False,
            length=50,
            values_callable=_values,
        ),
        nullable=False,
        server_default=InvitationStatus.PENDING.value,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Who sent it. Kept for the audit trail; nullable so that removing the
    # inviter does not erase the record of the invitation.
    # Same as Membership.user_id: the constraint is in the database, with
    # ON DELETE SET NULL, not in the metadata.
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
