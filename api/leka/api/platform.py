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

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status

from leka.api.dependencies import (
    MembershipResolverDep,
    PrincipalDep,
    SessionDep,
    SessionStoreDep,
    UserIdDep,
    WorkspaceRepositoryDep,
    WorkspaceServiceDep,
)
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.core import languages
from leka.core.errors import ErrorCode
from leka.db import SortableField, system_scope
from leka.governance import Permission, Principal, Target, audit_as, require_permission
from leka.identity import UserRepository
from leka.platform import (
    MAX_LOGO_BYTES,
    CurrentWorkspace,
    DeletionScheduled,
    LogoRefusedError,
    ObjectNotFoundError,
    ObjectStoreError,
    Role,
    Workspace,
    WorkspaceCreate,
    WorkspaceId,
    WorkspaceRead,
    WorkspaceStatus,
    WorkspaceSummary,
    WorkspaceUpdate,
    drop_logo,
    keep_logo,
    logo_of,
    object_store,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    user_id: UserIdDep,
    workspaces: WorkspaceServiceDep,
    db: SessionDep,
) -> WorkspaceRead:
    """Create a workspace and become its owner.

    No principal: this is the one tenancy action performed by someone who is
    not yet in any workspace.
    """
    # The language said, else its creator's, else the catalogue's default:
    # what its shared words will be written in.
    creator = await UserRepository(db).get(user_id)
    workspace = await workspaces.create(
        payload.name,
        owner_user_id=user_id,
        default_language=payload.default_language
        or (creator.language if creator else None)
        or languages.catalogue().default,
    )
    return WorkspaceRead.model_validate(workspace)


# What /workspaces may be sorted by.
#
# name is what a switcher shows, so it is the default. uq_workspaces_slug
# backs a slug sort; name and created_at have no index and do not need one
# — a person belongs to a handful of workspaces, and the query is already
# restricted to their own memberships.
WORKSPACE_SORTS = SortCatalogue(
    fields=(
        SortableField("name", Workspace.name, "no index; bounded by the caller's memberships"),
        SortableField("slug", Workspace.slug, "uq_workspaces_slug"),
        SortableField("created_at", Workspace.created_at, "no index; same bound as name"),
    ),
    default="name",
)


@router.get("", response_model=PageEnvelope[WorkspaceSummary])
async def list_my_workspaces(
    user_id: UserIdDep,
    memberships: MembershipResolverDep,
    page: PageParams,
    db: SessionDep,
    status: Annotated[
        WorkspaceStatus | None, Query(description="Only workspaces in this state.")
    ] = None,
) -> PageEnvelope[WorkspaceSummary]:
    """Every workspace I may enter. What fills the switcher.

    system_scope here rather than inside the repository, because this is the
    one question asked before any workspace exists in the request: which
    ones may this person enter at all. Declared at the call site, in one
    visible line, which is what that context manager is for.
    """
    statement = memberships.workspaces_for_user(user_id)
    if status is not None:
        statement = statement.where(Workspace.status == status)

    with system_scope():
        result = await serve_page(
            db,
            statement,
            request=page,
            catalogue=WORKSPACE_SORTS,
            id_column=Workspace.id,
        )
        roles = await memberships.roles_in(user_id, [row.id for row in result.items])

    return PageEnvelope(
        data=[
            WorkspaceSummary(
                id=workspace.id,
                name=workspace.name,
                slug=workspace.slug,
                status=workspace.status,
                role=roles[workspace.id],
                demo=workspace.demo,
            )
            for workspace in result.items
        ],
        next_cursor=result.next_cursor,
    )


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
    db: SessionDep,
) -> WorkspaceRead:
    """Rename or reconfigure. Admin or above."""
    workspace = await repository.get(principal.workspace_id)
    if workspace is None:  # pragma: no cover
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    before, language_before = workspace.name, workspace.default_language
    # The workspace's preferences as sent, read off the payload: an alias of
    # its `settings` would look, to test_secret_access, like leka's config.
    preferences = payload.model_dump(mode="json", by_alias=True, exclude_unset=True).get("settings")
    updated = await workspaces.configure(
        workspace,
        name=payload.name,
        settings=preferences,
        default_language=payload.default_language,
    )
    audit_as(
        db,
        principal,
        "workspace",
        "workspace.updated",
        target=Target("workspace", workspace.id, updated.name),
        detail={
            **(
                {"name": {"before": before, "after": updated.name}}
                if before != updated.name
                else {}
            ),
            **({"settings": sorted(preferences)} if preferences else {}),
            **(
                {
                    "default_language": {
                        "before": language_before,
                        "after": updated.default_language,
                    }
                }
                if language_before != updated.default_language
                else {}
            ),
        },
    )
    return WorkspaceRead.model_validate(updated)


Admin = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))]
Member = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
LOGO_REFUSED = {
    "unsupported_type": (status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "A PNG, JPEG or WebP image."),
    "too_large": (status.HTTP_413_CONTENT_TOO_LARGE, "512 KB at most."),
    "empty": (status.HTTP_422_UNPROCESSABLE_CONTENT, "The image is empty."),
    "not_what_it_says": (status.HTTP_422_UNPROCESSABLE_CONTENT, "Not the image its type says."),
}


def _store_down() -> ApiError:
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorCode.SERVICE_UNAVAILABLE,
        "The image could not be kept now: try again.",
    )


@router.put(
    "/current/logo",
    response_model=WorkspaceRead,
    summary="The organisation's logo, given by its admin",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in ("image/png", "image/jpeg", "image/webp")
            },
        }
    },
)
async def give_logo(
    request: Request,
    principal: Admin,
    repository: WorkspaceRepositoryDep,
    db: SessionDep,
    content_type: Annotated[str, Header(alias="Content-Type")] = "",
    content_length: Annotated[int | None, Header(alias="Content-Length")] = None,
) -> WorkspaceRead:
    """Its bytes the body (2026-10-25): a PNG, JPEG or WebP image, 512 KB at
    most, its bytes what its type says — 415, 413 or 422 otherwise, nothing
    kept. Shown in the header instead of its name; the one before removed."""
    status_code, message = LOGO_REFUSED["too_large"]
    if content_length is not None and content_length > MAX_LOGO_BYTES:
        raise ApiError(status_code, ErrorCode.VALIDATION_FAILED, message)
    payload = b""
    async for chunk in request.stream():
        payload += chunk
        if len(payload) > MAX_LOGO_BYTES:
            raise ApiError(status_code, ErrorCode.VALIDATION_FAILED, message)
    workspace = await repository.get(principal.workspace_id)
    if workspace is None:  # pragma: no cover
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    try:
        await keep_logo(workspace, payload, content_type=content_type, store=object_store())
    except LogoRefusedError as error:
        code, said = LOGO_REFUSED[error.code]
        raise ApiError(code, ErrorCode.VALIDATION_FAILED, said) from error
    except ObjectStoreError as error:
        raise _store_down() from error
    audit_as(
        db,
        principal,
        "workspace",
        "workspace.logo_changed",
        target=Target("workspace", workspace.id, workspace.name),
        detail={"type": content_type.split(";")[0].strip().lower(), "bytes": len(payload)},
    )
    return WorkspaceRead.model_validate(workspace)


@router.delete(
    "/current/logo",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="The logo removed: its name again",
)
async def remove_logo(
    principal: Admin, repository: WorkspaceRepositoryDep, db: SessionDep
) -> Response:
    workspace = await repository.get(principal.workspace_id)
    if workspace is None:  # pragma: no cover
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    try:
        removed = await drop_logo(workspace, store=object_store())
    except ObjectStoreError as error:
        raise _store_down() from error
    if removed:
        audit_as(
            db,
            principal,
            "workspace",
            "workspace.logo_removed",
            target=Target("workspace", workspace.id, workspace.name),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/current/logo",
    response_class=Response,
    summary="The organisation's logo, for its members",
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}}},
)
async def read_logo(principal: Member, repository: WorkspaceRepositoryDep) -> Response:
    """Its image — 404 without one: its name is shown instead."""
    workspace = await repository.get(principal.workspace_id)
    said = logo_of(workspace) if workspace is not None else None
    if said is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No logo: its name.")
    try:
        payload = b"".join([chunk async for chunk in object_store().get(said["key"])])
    except ObjectNotFoundError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No logo.") from error
    except ObjectStoreError as error:
        raise _store_down() from error
    return Response(
        payload,
        media_type=said["type"],
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


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
        demo=workspace.demo,
    )


@router.delete("/current", response_model=DeletionScheduled)
async def request_workspace_deletion(
    principal: Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_DELETE))],
    workspaces: WorkspaceServiceDep,
    repository: WorkspaceRepositoryDep,
    db: SessionDep,
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
    audit_as(
        db,
        principal,
        "workspace",
        "workspace.deletion_requested",
        target=Target("workspace", workspace.id, workspace.name),
        detail={"erasure_due_at": due.isoformat()},
    )
    return DeletionScheduled(
        workspace_id=scheduled.id,
        deletion_requested_at=scheduled.deletion_requested_at,
        erasure_due_at=due,
    )


# Role is re-exported for the routers that annotate with it.
__all__ = ["Role", "router"]
