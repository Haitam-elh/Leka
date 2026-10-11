"""Tenancy: creating workspaces, managing seats, ending an account.

Everything a workspace goes through, from the first signup to the GDPR
deletion, lives here. What a role is ALLOWED to do is leka.governance; this
module performs the action once that question is answered.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import enqueue
from leka.db import system_scope, workspace_scope
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
    WorkspaceRepository,
)

# How long a customer has to change their mind after asking for deletion.
DELETION_GRACE_PERIOD = timedelta(days=30)

# Long enough that guessing is hopeless, short enough to survive an email
# client's line wrapping.
INVITATION_TOKEN_BYTES = 32
INVITATION_LIFETIME = timedelta(days=7)

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class TenancyError(Exception):
    """A tenancy operation was refused. Carries why."""


def slugify(name: str) -> str:
    """A URL-safe handle for a workspace name."""
    slug = _SLUG_PATTERN.sub("-", name.strip().lower()).strip("-")
    return slug or "workspace"


def hash_token(token: str) -> str:
    """What we store for an invitation token.

    sha256 rather than a password hash: this value is high-entropy and
    short-lived, so the slow hashing that protects guessable passwords buys
    nothing here. What matters is that the database never holds the token
    itself — a leaked backup must not be a set of usable invitations.
    """
    return hashlib.sha256(token.encode()).hexdigest()


class WorkspaceService:
    """The life of a tenant."""

    def __init__(self, workspaces: WorkspaceRepository, session: AsyncSession) -> None:
        # The session is taken explicitly rather than reached for inside the
        # repository: creating a workspace has to build a second, scoped
        # repository for its owner's membership, and a service that pokes at
        # another object's private attribute is a service that breaks when
        # that object is refactored.
        self._workspaces = workspaces
        self._session = session

    async def create(
        self, name: str, owner_user_id: uuid.UUID, *, default_language: str | None = None
    ) -> Workspace:
        """Create a workspace and seat its owner, in one transaction.

        The two are inseparable: a workspace with no owner is unusable and
        undeletable. Doing it in one call is also why Membership lives in
        this module rather than in governance — a route may call one service,
        not two (architecture rule 6).
        """
        slug = await self._unique_slug(slugify(name))
        workspace = await self._workspaces.create(name=name, slug=slug)
        if default_language is not None:
            workspace.default_language = default_language

        # The workspace now exists, so its scope can be entered — which the
        # membership write needs, since memberships are workspace-scoped.
        with workspace_scope(workspace.id):
            memberships = MembershipRepository(self._session, workspace.id)
            memberships.create(user_id=owner_user_id, role=Role.OWNER)
            await memberships.flush()

        return workspace

    async def _unique_slug(self, base: str) -> str:
        """Two companies may both be called Acme."""
        candidate = base
        for _ in range(5):
            if await self._workspaces.get_by_slug(candidate) is None:
                return candidate
            candidate = f"{base}-{secrets.token_hex(3)}"
        msg = "could not find a free slug for this workspace name"
        raise TenancyError(msg)

    async def configure(
        self,
        workspace: Workspace,
        *,
        name: str | None = None,
        settings: dict[str, object] | None = None,
        default_language: str | None = None,
    ) -> Workspace:
        """Update a workspace's name or settings.

        The slug is NOT regenerated when the name changes: it may already be
        in links, bookmarks and other people's documentation.
        """
        if name is not None:
            workspace.name = name
        if settings is not None:
            workspace.settings = {**workspace.settings, **settings}
        if default_language is not None:
            workspace.default_language = default_language
        return workspace

    async def suspend(self, workspace: Workspace) -> Workspace:
        """Pause writing. Reading keeps working, and so does the bill."""
        workspace.status = WorkspaceStatus.SUSPENDED
        workspace.suspended_at = datetime.now(UTC)
        return workspace

    async def reactivate(self, workspace: Workspace) -> Workspace:
        workspace.status = WorkspaceStatus.ACTIVE
        workspace.suspended_at = None
        workspace.deletion_requested_at = None
        return workspace

    async def request_deletion(self, workspace: Workspace) -> Workspace:
        """Start the grace period.

        Access stops immediately; the data stays. A customer who changes
        their mind within DELETION_GRACE_PERIOD loses nothing, and one who
        does not gets a real erasure.
        """
        workspace.status = WorkspaceStatus.PENDING_DELETION
        workspace.deletion_requested_at = datetime.now(UTC)
        return workspace

    def deletion_due_at(self, workspace: Workspace) -> datetime | None:
        if workspace.deletion_requested_at is None:
            return None
        return workspace.deletion_requested_at + DELETION_GRACE_PERIOD

    async def erase(self, workspace: Workspace) -> None:
        """Delete a customer's data, permanently.

        One DELETE: every business table cascades from workspaces. The
        guarantee is in the schema, not in a script that has to remember
        every table — and a table added next year inherits it for free.

        THE CASCADE DOES NOT REACH THE OBJECT STORE. It removes the ROWS in
        raw_payloads; the bytes those rows pointed at are untouched, because
        nothing in PostgreSQL can reach a bucket. Leaving it there would mean
        a deleted customer's data stays with us for ever — an erasure that
        did not happen, and a bill for it.

        So the objects are purged too, on the queue rather than here: a
        workspace can hold hundreds of thousands of them and a request must
        not wait. If the queue is unreachable the attempt is logged and the
        deletion still goes through; leka.ingestion.tasks.reconcile finds
        whatever was left behind. See docs/data-lifecycle.md.
        """
        workspace_id = str(workspace.id)
        await self._workspaces.delete(workspace)
        await enqueue("leka.platform.tasks.run_purge_workspace_objects", workspace_id)


class LastOwnerError(TenancyError):
    """Closing this account would leave a workspace others use with no owner."""

    def __init__(self, workspace_name: str) -> None:
        super().__init__(f"last owner of {workspace_name!r}")
        self.workspace_name = workspace_name


class AccountClosure:
    """What a person leaves behind when they close their account.

    Their seats go with them (memberships cascade from users). What needs
    deciding first is what they OWN:

    - a workspace they are alone in is theirs alone: it starts its deletion,
      the same grace period and the same erasure as any deletion
      (WorkspaceService.request_deletion), so a mistake is still reversible
      by support for DELETION_GRACE_PERIOD;
    - a workspace others use, of which they are the last owner, would be
      left with nobody who can administer it: refused, by name, until they
      hand it over.

    Nothing is written before every workspace has been checked: a refusal
    leaves the account and all its workspaces exactly as they were.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workspaces = WorkspaceService(WorkspaceRepository(session), session)

    async def close(self, user_id: uuid.UUID) -> list[Workspace]:
        """Check, then start the deletion of the workspaces left empty.
        Returns them. Raises LastOwnerError, having changed nothing."""
        with system_scope():
            result = await self._session.execute(
                select(Workspace, Membership)
                .join(Membership, Membership.workspace_id == Workspace.id)
                .where(Membership.user_id == user_id)
            )
            seats = list(result.tuples())
        alone: list[Workspace] = []
        for workspace, membership in seats:
            if membership.role is not Role.OWNER:
                continue
            with workspace_scope(workspace.id):
                memberships = MembershipRepository(self._session, workspace.id)
                if await memberships.count_members() == 1:
                    alone.append(workspace)
                elif await memberships.count_owners() == 1:
                    raise LastOwnerError(workspace.name)
        for workspace in alone:
            await self._workspaces.request_deletion(workspace)
        return alone


class InvitationAcceptance:
    """Accepting an invitation, from outside every workspace.

    A separate service because the invitee is, by definition, not yet a
    member of the workspace they are joining. Everything else in this module
    runs behind a Principal, which requires a membership — requiring one here
    would mean you had to already be in the workspace to be let in.

    The token is the only credential involved. It is looked up across
    tenants, which is stated with system_scope rather than left implicit.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def accept(self, token: str, user_id: uuid.UUID) -> Membership | None:
        """Consume a token and create the seat it promises.

        Returns None for every failure — never existed, already used,
        expired, or the person is already a member. One outcome for all of
        them, so that a caller cannot probe for live tokens.
        """
        with system_scope():
            result = await self._session.execute(
                select(Invitation).where(Invitation.token_hash == hash_token(token))
            )
            invitation = result.scalar_one_or_none()

        if invitation is None or not MembershipService.is_acceptable(invitation):
            return None

        with workspace_scope(invitation.workspace_id):
            memberships = MembershipRepository(self._session, invitation.workspace_id)
            if await memberships.get_for_user(user_id) is not None:
                # Already seated. Consume the invitation anyway so the token
                # cannot be handed to someone else.
                invitation.status = InvitationStatus.REVOKED
                await memberships.flush()
                return None

            invitation.status = InvitationStatus.ACCEPTED
            invitation.accepted_at = datetime.now(UTC)
            membership = memberships.create(user_id=user_id, role=invitation.role)
            await memberships.flush()
            return membership


class MembershipService:
    """Seats and invitations, inside one workspace."""

    def __init__(
        self,
        memberships: MembershipRepository,
        invitations: InvitationRepository,
    ) -> None:
        self._memberships = memberships
        self._invitations = invitations

    async def invite(self, email: str, role: Role, invited_by: uuid.UUID) -> tuple[Invitation, str]:
        """Create an invitation and return it with its CLEAR token.

        The clear token is returned once, to be emailed, and never stored.
        Losing it means re-inviting — which is the correct trade for a
        database that cannot be turned into a set of usable invitations.
        """
        existing = await self._invitations.get_pending_for_email(email)
        if existing is not None:
            # Re-inviting replaces rather than accumulating, so revoking one
            # invitation does not leave two others alive.
            existing.status = InvitationStatus.REVOKED

        token = secrets.token_urlsafe(INVITATION_TOKEN_BYTES)
        invitation = Invitation(
            email=email,
            role=role,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + INVITATION_LIFETIME,
            invited_by_user_id=invited_by,
        )
        self._invitations.add(invitation)
        await self._invitations.flush()
        return invitation, token

    @staticmethod
    def is_acceptable(invitation: Invitation, *, now: datetime | None = None) -> bool:
        """Pending, and not expired. Both, every time."""
        moment = now or datetime.now(UTC)
        return invitation.status is InvitationStatus.PENDING and invitation.expires_at > moment

    async def accept(self, invitation: Invitation, user_id: uuid.UUID) -> Membership:
        """Turn an invitation into a seat.

        Single use: the invitation is marked accepted in the same transaction
        as the membership is created, so a token replayed a second time finds
        a row that is no longer pending.
        """
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(UTC)
        membership = self._memberships.create(user_id=user_id, role=invitation.role)
        await self._memberships.flush()
        return membership

    async def change_role(self, membership: Membership, role: Role) -> Membership:
        membership.role = role
        return membership

    async def remove(self, membership: Membership) -> None:
        """Remove a seat.

        Takes effect on the person's next request, because the principal is
        resolved from this table every time rather than cached at sign-in.
        """
        await self._memberships.delete(membership)

    async def would_orphan_the_workspace(self, membership: Membership) -> bool:
        """True if removing or demoting this seat leaves no owner."""
        if membership.role is not Role.OWNER:
            return False
        return await self._memberships.count_owners() <= 1
