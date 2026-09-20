"""Members and invitations: who may enter the active workspace, and as what.

Every route is scoped to the caller's ACTIVE workspace, taken from the
principal. None of them accepts a workspace identifier — there is no
parameter through which a caller could point one at someone else's tenant.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from leka.api.dependencies import (
    InvitationAcceptanceDep,
    MembershipRepositoryDep,
    MembershipServiceDep,
    PrincipalDep,
    UserIdDep,
)
from leka.governance import Permission, Principal, require_permission
from leka.platform import (
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    MemberRead,
    MemberRoleUpdate,
    Membership,
)

router = APIRouter(tags=["members"])


@router.get("/members", response_model=list[MemberRead])
async def list_members(
    principal: PrincipalDep,
    memberships: MembershipRepositoryDep,
) -> list[MemberRead]:
    """Everyone with a seat in the active workspace."""
    seats = await memberships.list_all()
    return [MemberRead.model_validate(seat) for seat in seats]


@router.post(
    "/members/invite",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    payload: InvitationCreate,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_INVITE))],
    members: MembershipServiceDep,
) -> InvitationCreated:
    """Invite someone by email. Admin or above.

    The response carries the clear token exactly once, so it can be emailed.
    It is never stored and no other route will return it again.
    """
    invitation, token = await members.invite(
        payload.email, payload.role, invited_by=principal.user_id
    )
    return InvitationCreated(invitation=InvitationRead.model_validate(invitation), token=token)


@router.patch("/members/{membership_id}", response_model=MemberRead)
async def change_member_role(
    membership_id: uuid.UUID,
    payload: MemberRoleUpdate,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_UPDATE_ROLE))],
    memberships: MembershipRepositoryDep,
    members: MembershipServiceDep,
) -> MemberRead:
    """Change someone's role. Admin or above."""
    seat = await _seat_or_404(memberships, membership_id)
    if payload.role is not seat.role and await members.would_orphan_the_workspace(seat):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the last owner. Promote another owner first.",
        )
    return MemberRead.model_validate(await members.change_role(seat, payload.role))


@router.delete("/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    membership_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_REMOVE))],
    memberships: MembershipRepositoryDep,
    members: MembershipServiceDep,
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
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invitations/{token}/accept", response_model=MemberRead)
async def accept_invitation(
    token: str,
    user_id: UserIdDep,
    acceptance: InvitationAcceptanceDep,
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
