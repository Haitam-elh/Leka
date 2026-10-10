"""Members and invitations: who may enter the active workspace, and as what.

Every route is scoped to the caller's ACTIVE workspace, taken from the
principal. None of them accepts a workspace identifier — there is no
parameter through which a caller could point one at someone else's tenant.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status

from leka.api.dependencies import (
    InvitationAcceptanceDep,
    MembershipRepositoryDep,
    MembershipServiceDep,
    PrincipalDep,
    SessionDep,
    UserIdDep,
)
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.db import SortableField
from leka.governance import (
    PendingInvitationRead,
    Permission,
    Principal,
    Target,
    TeamMemberRead,
    audit,
    audit_as,
    inviter_name,
    pending_invitations,
    require_permission,
    revoke_invitation,
    team_members,
)
from leka.identity import DeferredEmailSender, build_email_sender, invitation_message
from leka.platform import (
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    MemberRead,
    MemberRoleUpdate,
    Membership,
    Role,
    Workspace,
)

router = APIRouter(tags=["members"])

# What /members may be sorted by, and what supports each one.
#
# created_at has no index of its own, and that is a deliberate exception
# rather than an oversight: the query is already restricted to one
# workspace by an indexed column, and a workspace holds tens of members. A
# sort of twenty rows in memory costs nothing. The rule matters for the
# tables that grow without bound — raw_payloads and entities already carry
# the composite indexes their sorts need.
MEMBER_SORTS = SortCatalogue(
    fields=(
        SortableField("created_at", Membership.created_at, "no index; bounded by workspace_id"),
        SortableField("role", Membership.role, "no index; bounded by workspace_id"),
    ),
    default="created_at",
)


@router.get("/members", response_model=PageEnvelope[MemberRead])
async def list_members(
    principal: PrincipalDep,
    memberships: MembershipRepositoryDep,
    page: PageParams,
    db: SessionDep,
    role: Annotated[Role | None, Query(description="Only seats with this role.")] = None,
) -> PageEnvelope[MemberRead]:
    """Everyone with a seat in the active workspace.

    `role` is a DECLARED, TYPED parameter, which is what makes filtering a
    whitelist here: a value outside the enumeration is refused by FastAPI
    before this function runs, and there is no path by which a query string
    becomes a column name. Adding a filter means adding a parameter, on
    purpose.
    """
    statement = memberships.select(Membership)
    if role is not None:
        statement = statement.where(Membership.role == role)

    result = await serve_page(
        db,
        statement,
        request=page,
        catalogue=MEMBER_SORTS,
        id_column=Membership.id,
    )
    return PageEnvelope(
        data=[MemberRead.model_validate(seat) for seat in result.items],
        next_cursor=result.next_cursor,
    )


@router.post(
    "/members/invite",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    payload: InvitationCreate,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_INVITE))],
    members: MembershipServiceDep,
    db: SessionDep,
    background: BackgroundTasks,
) -> InvitationCreated:
    """Invite someone by email. Admin or above.

    The invitation is emailed once the request has committed — its link,
    who invites, to which workspace, as what. The response carries the
    clear token exactly once too, for whoever must pass it on by hand; it
    is never stored and no other route will return it again.
    """
    invitation, token = await members.invite(
        payload.email, payload.role, invited_by=principal.user_id
    )
    audit_as(
        db,
        principal,
        "team",
        "member.invited",
        # Never the address: personal data the trail would keep for years.
        target=Target("invitation", invitation.id),
        detail={"role": invitation.role.value},
    )
    workspace = await db.get(Workspace, principal.workspace_id)
    await DeferredEmailSender(build_email_sender(), background.add_task).send(
        invitation_message(
            invitation.email,
            token,
            workspace=workspace.name if workspace else "LEKA",
            inviter=await inviter_name(db, principal.user_id),
            role=invitation.role.value,
        )
    )
    return InvitationCreated(invitation=InvitationRead.model_validate(invitation), token=token)


@router.get("/team/members", response_model=list[TeamMemberRead])
async def team(principal: PrincipalDep, db: SessionDep) -> list[TeamMemberRead]:
    """Everyone with a seat, as Équipe & accès shows them: name, address,
    role, when they joined and last signed in."""
    return await team_members(db, principal.workspace_id)


@router.get("/invitations", response_model=list[PendingInvitationRead])
async def invitations(
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_INVITE))],
    db: SessionDep,
) -> list[PendingInvitationRead]:
    """The invitations still waiting — the expired said so."""
    return await pending_invitations(db, principal.workspace_id)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke(
    invitation_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_INVITE))],
    db: SessionDep,
) -> Response:
    """Revoked: its link no longer works."""
    if not await revoke_invitation(db, principal.workspace_id, invitation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such pending invitation.")
    audit_as(
        db, principal, "team", "invitation.revoked", target=Target("invitation", invitation_id)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/members/{membership_id}", response_model=MemberRead)
async def change_member_role(
    membership_id: uuid.UUID,
    payload: MemberRoleUpdate,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_UPDATE_ROLE))],
    memberships: MembershipRepositoryDep,
    members: MembershipServiceDep,
    db: SessionDep,
) -> MemberRead:
    """Change someone's role. Admin or above."""
    seat = await _seat_or_404(memberships, membership_id)
    if payload.role is not seat.role and await members.would_orphan_the_workspace(seat):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the last owner. Promote another owner first.",
        )
    before = seat.role.value
    changed = await members.change_role(seat, payload.role)
    audit_as(
        db,
        principal,
        "team",
        "member.role_changed",
        target=Target("user", seat.user_id),
        detail={"before": before, "after": payload.role.value},
    )
    return MemberRead.model_validate(changed)


@router.delete("/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    membership_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_REMOVE))],
    memberships: MembershipRepositoryDep,
    members: MembershipServiceDep,
    db: SessionDep,
) -> Response:
    """Remove a seat. Admin or above.

    Takes effect on that person's next request: the principal is resolved
    from this table every time, never cached at sign-in.
    """
    seat = await _seat_or_404(memberships, membership_id)
    if await members.would_orphan_the_workspace(seat):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the last owner. Promote another owner first.",
        )
    await members.remove(seat)
    audit_as(
        db,
        principal,
        "team",
        "member.removed",
        target=Target("user", seat.user_id),
        detail={"role": seat.role.value},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invitations/{token}/accept", response_model=MemberRead)
async def accept_invitation(
    token: str,
    user_id: UserIdDep,
    acceptance: InvitationAcceptanceDep,
    db: SessionDep,
) -> MemberRead:
    """Turn an invitation into a seat.

    No Principal, deliberately. The invitee is by definition not yet a member
    of the workspace they are joining; requiring a principal would mean
    having to be inside in order to be let in. The token is the credential.

    LEKA-330 owns creating the account: by the time this runs the caller is
    authenticated, and this route does only the workspace half.

    Single use and time limited. One refusal covers "never existed",
    "already used" and "expired", so a caller cannot probe for live tokens.
    """
    membership = await acceptance.accept(token, user_id)
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This invitation is not valid.")
    audit(
        db,
        membership.workspace_id,
        "team",
        "member.joined",
        actor_id=user_id,
        actor_role=membership.role.value,
        target=Target("user", user_id),
    )
    return MemberRead.model_validate(membership)


async def _seat_or_404(
    memberships: MembershipRepositoryDep, membership_id: uuid.UUID
) -> Membership:
    """Fetch a seat from the ACTIVE workspace, or refuse.

    The repository is scoped, so a membership id belonging to another
    workspace simply is not found — a caller cannot reach across by guessing
    an identifier.
    """
    seat = await memberships.get(Membership, membership_id)
    if seat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such member.")
    return seat
