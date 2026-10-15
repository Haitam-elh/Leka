"""What a plan allows besides its AI credits (LEKA-463): its users and its
sources, read from the catalogue. At the limit, one more is refused and the
plan that allows it is named — chosen explicitly, never changed for them.

    room_for_user(session, workspace, email)   a seat or a pending invitation more
    room_for_source(session, workspace)        a source more
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing.catalogue import catalogue
from leka.connectors import Source
from leka.governance.plans import plan_of
from leka.platform import Invitation, InvitationStatus, Membership

Limited = Literal["users", "sources"]


class PlanLimitError(Exception):
    """One more than the plan allows: which plan, its limit, the one above."""

    def __init__(self, what: Limited, plan: str, limit: int, upgrade: str | None) -> None:
        self.what, self.plan, self.limit, self.upgrade = what, plan, limit, upgrade
        then = f" {upgrade.capitalize()} allows more." if upgrade else ""
        super().__init__(f"The {plan.capitalize()} plan allows {limit} {what}.{then}")


async def _room(session: AsyncSession, workspace_id: uuid.UUID, what: Limited, used: int) -> None:
    plans = catalogue().plans
    current = (await plan_of(session, workspace_id)).name
    limit = getattr(catalogue().plan(current).quotas, what)
    if limit is None or used < limit:
        return
    keys: list[str] = [p.key for p in plans]
    above = plans[keys.index(current) + 1 :]
    allows = [(p.key, getattr(p.quotas, what)) for p in above]
    roomy = (key for key, most in allows if most is None or most > used)
    upgrade = next(roomy, None)
    raise PlanLimitError(what, current, limit, upgrade)


async def room_for_user(session: AsyncSession, workspace_id: uuid.UUID, email: str) -> None:
    seats = await session.scalar(
        select(func.count()).select_from(Membership).where(Membership.workspace_id == workspace_id)
    )
    # Re-inviting an address replaces its invitation: not one more.
    pending = await session.scalar(
        select(func.count())
        .select_from(Invitation)
        .where(
            Invitation.workspace_id == workspace_id,
            Invitation.status == InvitationStatus.PENDING,
            Invitation.expires_at > datetime.now(UTC),
            func.lower(Invitation.email) != email.lower(),
        )
    )
    await _room(session, workspace_id, "users", int(seats or 0) + int(pending or 0))


async def room_for_source(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    used = await session.scalar(
        select(func.count()).select_from(Source).where(Source.workspace_id == workspace_id)
    )
    await _room(session, workspace_id, "sources", int(used or 0))
