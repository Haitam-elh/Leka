"""What a person asks of those who may decide (LEKA-527): one who may not
change the workspace's plan asks its admins to, from the AI capacity's
prompt — told in the centre to whoever may pay, once a month for each
threshold and person."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.notifications.models import Notification
from leka.notifications.repository import NotificationRepository, Told

# Who may change the plan: who may update the workspace (billing has no
# permission of its own).
PAYER = "workspace:update"


def _key(period: date, threshold: int, by: uuid.UUID) -> str:
    return f"billing.upgrade_asked:{period.isoformat()}:{threshold}:{by}"


async def ask_for_upgrade(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    by: uuid.UUID,
    name: str,
    plan_key: str | None,
    plan_name: str | None,
    threshold: int,
    period: date,
    now: datetime,
) -> bool:
    """The admins told that `by` asks for the plan that gives more credits —
    once: asked again, nothing more. False when already asked."""
    kept = await NotificationRepository(session, workspace_id).keep(
        [
            Told(
                key=_key(period, threshold, by),
                category="billing",
                kind="billing.upgrade_asked",
                severity="warning" if threshold >= 100 else "info",
                occurred_at=now,
                params={"name": name, "plan": plan_name, "threshold": threshold},
                link=f"/billing/plans?plan={plan_key}" if plan_key else "/billing",
                to_permission=PAYER,
            )
        ]
    )
    return kept > 0


async def upgrade_asked(
    session: AsyncSession, workspace_id: uuid.UUID, *, by: uuid.UUID, threshold: int, period: date
) -> bool:
    """Whether `by` already asked, for this threshold, this month."""
    found = await session.scalar(
        select(Notification.id).where(
            Notification.workspace_id == workspace_id,
            Notification.event_key == _key(period, threshold, by),
        )
    )
    return found is not None


__all__ = ["ask_for_upgrade", "upgrade_asked"]
