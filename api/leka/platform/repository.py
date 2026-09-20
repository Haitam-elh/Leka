"""Database access for the platform module.

The only place in this module where a query is written (architecture rule 4).

Three of the four classes here are WorkspaceScopedRepository subclasses:
they operate inside a workspace and cannot be built without one.

MembershipResolver is the exception, and deliberately so. It answers the
questions asked *before* a workspace is settled — "may this person enter
here?", "where may this person go?" — so it cannot be constructed with the
answer it is about to produce. It lives here rather than in governance
because this module owns the Membership model, and the module that owns a
model owns its queries.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.db import WorkspaceScopedRepository, system_scope, workspace_scope
from leka.platform.models import (
    Invitation,
    InvitationStatus,
    Membership,
    Role,
    Workspace,
)


class MembershipResolver:
    """Answers where a person may go, before any workspace is chosen."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_user_in_workspace(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Membership | None:
        """The seat this person holds in this workspace, if any.

        Scoped to the *claimed* workspace before the query runs, so the scope
        guard adds `workspace_id = :claimed` itself. No seat there means None,
        and the caller refuses — the claim never becomes an assertion.

        Read on every request rather than cached: that is what makes removing
        someone take effect immediately rather than at their next sign-in.
        """
        with workspace_scope(workspace_id):
            result = await self._session.execute(
                select(Membership).where(Membership.user_id == user_id)
            )
            return result.scalar_one_or_none()

    async def list_workspaces_for_user(
        self, user_id: uuid.UUID
    ) -> Sequence[tuple[Workspace, Membership]]:
        """Every workspace this person may enter.

        system_scope, legitimately: this is the one question asked before any
        workspace exists in the request. It fills the workspace switcher and
        tells a fresh session where it may go. It spans tenants along exactly
        one axis — this person's own memberships.
        """
        with system_scope():
            result = await self._session.execute(
                select(Workspace, Membership)
                .join(Membership, Membership.workspace_id == Workspace.id)
                .where(Membership.user_id == user_id)
                .order_by(Workspace.name)
            )
            return [(workspace, membership) for workspace, membership in result.all()]


class WorkspaceRepository:
    """Reads and writes rows in `workspaces`.

    Not workspace-scoped: the workspaces table has no workspace_id — it IS
    the workspace — and creating one necessarily happens before one exists.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str, slug: str) -> Workspace:
        workspace = Workspace(name=name, slug=slug)
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def get(self, workspace_id: uuid.UUID) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    async def get_by_slug(self, slug: str) -> Workspace | None:
        result = await self._session.execute(select(Workspace).where(Workspace.slug == slug))
        return result.scalar_one_or_none()

    async def delete(self, workspace: Workspace) -> None:
        """Erase a customer.

        Every business table cascades from workspaces, so this one DELETE
        removes the lot. That is the GDPR obligation, met by the schema
        rather than by a script that has to remember every table.
        """
        await self._session.delete(workspace)


class MembershipRepository(WorkspaceScopedRepository):
    """Seats inside one workspace."""

    async def list_all(self) -> Sequence[Membership]:
        return await self.list(self.select(Membership))

    async def get_for_user(self, user_id: uuid.UUID) -> Membership | None:
        result = await self._session.execute(
            self.select(Membership).where(Membership.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def count_owners(self) -> int:
        """Used to refuse the last owner being demoted or removed.

        A workspace with no owner cannot be deleted, transferred or rescued —
        a support ticket created by one careless click.
        """
        result = await self._session.execute(
            self.select(Membership).where(Membership.role == Role.OWNER)
        )
        return len(result.scalars().all())

    def create(self, user_id: uuid.UUID, role: Role) -> Membership:
        membership = Membership(user_id=user_id, role=role)
        self.add(membership)
        return membership


class InvitationRepository(WorkspaceScopedRepository):
    """Invitations inside one workspace."""

    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        """Look up a presented token.

        NOT workspace-filtered by the repository's own scope, because an
        invitee is by definition outside every workspace when they accept.
        The token hash is the credential; system_scope says so explicitly
        instead of leaving it implicit.
        """
        with system_scope():
            result = await self._session.execute(
                select(Invitation).where(Invitation.token_hash == token_hash)
            )
            return result.scalar_one_or_none()

    async def get_pending_for_email(self, email: str) -> Invitation | None:
        result = await self._session.execute(
            self.select(Invitation)
            .where(Invitation.email == email)
            .where(Invitation.status == InvitationStatus.PENDING)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[Invitation]:
        return await self.list(self.select(Invitation))
