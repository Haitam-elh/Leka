"""Composition: which objects a route is handed.

The API layer is the only place allowed to know about every module at once,
so the wiring lives here. In particular the repositories that need a
Principal cannot be built inside leka.platform — platform sits below
governance, and importing it would reverse the dependency graph
(architecture rule 1).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from leka.db import DatabaseSession

# Re-exported rather than redefined: one PrincipalDep, with its scope,
# for every route (see leka/governance/dependencies.py).
from leka.governance import PrincipalDep as PrincipalDep
from leka.platform import (
    InvitationAcceptance,
    InvitationRepository,
    MembershipRepository,
    MembershipResolver,
    MembershipService,
    SessionStore,
    UserId,
    WorkspaceRepository,
    WorkspaceService,
    get_current_user_id,
    get_session_store,
)

SessionDep = DatabaseSession
UserIdDep = Annotated[UserId, Depends(get_current_user_id)]
SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]


def get_workspace_service(session: SessionDep) -> WorkspaceService:
    """Tenancy operations that happen outside, or before, a workspace."""
    return WorkspaceService(WorkspaceRepository(session), session)


def get_workspace_repository(session: SessionDep) -> WorkspaceRepository:
    return WorkspaceRepository(session)


def get_membership_resolver(session: SessionDep) -> MembershipResolver:
    """Answers where a person may go, before a workspace is settled."""
    return MembershipResolver(session)


def get_membership_repository(session: SessionDep, principal: PrincipalDep) -> MembershipRepository:
    """Seats inside the caller's ACTIVE workspace.

    Scoped from the principal, never from a path parameter. That is rule 3
    made structural: there is no argument through which a caller could point
    this at someone else's workspace.
    """
    return MembershipRepository(session, principal.workspace_id)


def get_invitation_repository(session: SessionDep, principal: PrincipalDep) -> InvitationRepository:
    return InvitationRepository(session, principal.workspace_id)


def get_invitation_acceptance(session: SessionDep) -> InvitationAcceptance:
    """Accepting an invitation happens from outside every workspace, so this
    one takes no principal."""
    return InvitationAcceptance(session)


def get_membership_service(
    memberships: Annotated[MembershipRepository, Depends(get_membership_repository)],
    invitations: Annotated[InvitationRepository, Depends(get_invitation_repository)],
) -> MembershipService:
    return MembershipService(memberships, invitations)


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
WorkspaceRepositoryDep = Annotated[WorkspaceRepository, Depends(get_workspace_repository)]
MembershipResolverDep = Annotated[MembershipResolver, Depends(get_membership_resolver)]
MembershipRepositoryDep = Annotated[MembershipRepository, Depends(get_membership_repository)]
InvitationRepositoryDep = Annotated[InvitationRepository, Depends(get_invitation_repository)]
MembershipServiceDep = Annotated[MembershipService, Depends(get_membership_service)]
InvitationAcceptanceDep = Annotated[InvitationAcceptance, Depends(get_invitation_acceptance)]
