"""Workspaces: create, list, configure, switch, delete.

Every route validates, calls one service, and returns (architecture rule 6).
Permissions come from a dependency in the signature, never an `if` in the
body (rule 5).

The workspace is read from the server-side session, never from a path or a
body (rule 3). The one exception is /switch, and it is not really one: the
client ASKS to move, the server verifies a membership and then writes the id
into its own session. A client can request a workspace; it can never assert
that it is already in one.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from leka.api.dependencies import (
    MembershipResolverDep,
    PrincipalDep,
    SessionStoreDep,
    UserIdDep,
    WorkspaceRepositoryDep,
    WorkspaceServiceDep,
)
from leka.governance import Permission, Principal, require_permission
from leka.platform import (
    CurrentWorkspace,
    DeletionScheduled,
    Role,
    WorkspaceCreate,
    WorkspaceId,
    WorkspaceRead,
    WorkspaceSummary,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    user_id: UserIdDep,
    workspaces: WorkspaceServiceDep,
) -> WorkspaceRead:
    """Create a workspace and become its owner.

    No principal: this is the one tenancy action performed by someone who is
    not yet in any workspace.
    """
    workspace = await workspaces.create(payload.name, owner_user_id=user_id)
    return WorkspaceRead.model_validate(workspace)


@router.get("", response_model=list[WorkspaceSummary])
async def list_my_workspaces(
    user_id: UserIdDep,
    memberships: MembershipResolverDep,
) -> list[WorkspaceSummary]:
    """Every workspace I may enter. What fills the switcher."""
    pairs = await memberships.list_workspaces_for_user(user_id)
    return [
        WorkspaceSummary(
            id=workspace.id,
            name=workspace.name,
            slug=workspace.slug,
            status=workspace.status,
            role=membership.role,
        )
        for workspace, membership in pairs
    ]


@router.get("/current", response_model=CurrentWorkspace)
async def read_current_workspace(
    principal: PrincipalDep,
    workspaces: WorkspaceRepositoryDep,
) -> CurrentWorkspace:
    """The active workspace, my role in it, and what that role allows."""
    workspace = await workspaces.get(principal.workspace_id)
    if workspace is None:  # pragma: no cover - the principal proves it exists
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return CurrentWorkspace(
        workspace=WorkspaceRead.model_validate(workspace),
        role=principal.role,
        permissions=sorted(permission.value for permission in principal.permissions),
    )


@router.patch("/current", response_model=WorkspaceRead)
async def configure_current_workspace(
    payload: WorkspaceUpdate,
    principal: Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))],
    workspaces: WorkspaceServiceDep,
    repository: WorkspaceRepositoryDep,
) -> WorkspaceRead:
    """Rename or reconfigure. Admin or above."""
    workspace = await repository.get(principal.workspace_id)
    if workspace is None:  # pragma: no cover
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    updated = await workspaces.configure(workspace, name=payload.name, settings=payload.settings)
    return WorkspaceRead.model_validate(updated)


@router.post("/{workspace_id}/switch", response_model=WorkspaceSummary)
async def switch_workspace(
    workspace_id: uuid.UUID,
    request: Request,
    user_id: UserIdDep,
    memberships: MembershipResolverDep,
    store: SessionStoreDep,
    workspaces: WorkspaceRepositoryDep,
) -> WorkspaceSummary:
    """Move to another workspace I am a member of.

    The membership is verified BEFORE anything is written to the session. A
    caller who is not a member is refused and their session is untouched —
    the id in the path is a request, never a statement of fact.
    """
    membership = await memberships.get_for_user_in_workspace(user_id, workspace_id)
    workspace = await workspaces.get(workspace_id)
    if membership is None or workspace is None:
        # One answer for both cases: telling them apart would confirm which
        # workspace ids exist.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this workspace.")
    await store.set_active_workspace(request, WorkspaceId(workspace_id))
    return WorkspaceSummary(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        status=workspace.status,
        role=membership.role,
    )


@router.delete("/current", response_model=DeletionScheduled)
async def request_workspace_deletion(
    principal: Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_DELETE))],
    workspaces: WorkspaceServiceDep,
    repository: WorkspaceRepositoryDep,
) -> DeletionScheduled:
    """Ask for the workspace to be erased. Owner only.

    Starts a grace period rather than deleting: access stops now, the data
    goes later. A customer who changes their mind inside it loses nothing,
    and one who does not gets a real erasure.
    """
    workspace = await repository.get(principal.workspace_id)
    if workspace is None:  # pragma: no cover
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    scheduled = await workspaces.request_deletion(workspace)
    due = workspaces.deletion_due_at(scheduled)
    assert scheduled.deletion_requested_at is not None
    assert due is not None
    return DeletionScheduled(
        workspace_id=scheduled.id,
        deletion_requested_at=scheduled.deletion_requested_at,
        erasure_due_at=due,
    )


# Role is re-exported for the routers that annotate with it.
__all__ = ["Role", "router"]
