"""Who is in the workspace, and who is invited (Équipe & accès, mockup 15):
each member with their name, address, role and when they last signed in;
the invitations still waiting, who sent them, until when.

Read for the page; inviting, changing a role and removing stay
leka.platform's (MembershipService), behind their permissions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.identity import User
from leka.platform import Invitation, InvitationStatus, Membership, Role


class TeamMemberRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID  # the seat
    user_id: uuid.UUID
    role: Role
    joined_at: datetime
    email: str
    first_name: str | None
    last_name: str | None
    last_login_at: datetime | None


class PendingInvitationRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    email: str
    role: Role
    created_at: datetime
    expires_at: datetime
    expired: bool
    invited_by: str | None


def _name(first: str | None, last: str | None, email: str) -> str:
    return " ".join(part for part in (first, last) if part) or email


async def members(session: AsyncSession, workspace_id: uuid.UUID) -> list[TeamMemberRead]:
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(Membership.created_at)
    )
    return [
        TeamMemberRead(
            id=seat.id,
            user_id=user.id,
            role=seat.role,
            joined_at=seat.created_at,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            last_login_at=user.last_login_at,
        )
        for seat, user in rows.tuples().all()
    ]


async def pending(
    session: AsyncSession, workspace_id: uuid.UUID, *, now: datetime | None = None
) -> list[PendingInvitationRead]:
    """The invitations not accepted nor revoked — the expired said so."""
    moment = now or datetime.now(UTC)
    rows = await session.execute(
        select(Invitation, User)
        .outerjoin(User, User.id == Invitation.invited_by_user_id)
        .where(
            Invitation.workspace_id == workspace_id,
            Invitation.status == InvitationStatus.PENDING,
        )
        .order_by(Invitation.created_at.desc())
    )
    return [
        PendingInvitationRead(
            id=invitation.id,
            email=invitation.email,
            role=invitation.role,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
            expired=invitation.expires_at <= moment,
            invited_by=_name(user.first_name, user.last_name, user.email) if user else None,
        )
        for invitation, user in rows.tuples().all()
    ]


async def revoke(session: AsyncSession, workspace_id: uuid.UUID, invitation_id: uuid.UUID) -> bool:
    """A pending invitation revoked: its link no longer works."""
    found = await session.scalar(
        select(Invitation).where(
            Invitation.workspace_id == workspace_id,
            Invitation.id == invitation_id,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    if found is None:
        return False
    found.status = InvitationStatus.REVOKED
    await session.flush()
    return True


async def inviter_name(session: AsyncSession, user_id: uuid.UUID) -> str:
    user = await session.get(User, user_id)
    return _name(user.first_name, user.last_name, user.email) if user else "LEKA"
