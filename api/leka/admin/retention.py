"""LEKA ADMIN's own rows, kept as long as they serve and no longer (LEKA-546).

Every night (`admin-retention`, 04:25 UTC):
- the trail's protection checked first: its two triggers there and enabled.
  One missing or disabled is an error in the logs and a row of the trail
  (`admin.trail_unprotected`), and nothing of the trail is deleted that
  night;
- the trail older than settings.admin_audit_retention_days (a year)
  deleted: the one deletion it allows, which the database accepts only from
  this sweep and only past six months, said in the trail itself
  (`admin.trail_expired`);
- ended sessions (closed, or past their end) deleted after 30 days: a
  device list needs the open ones, and the trail keeps which session did
  what;
- codes used or expired deleted after 7 days.

The activity journal and the idempotency keys are the activity sweep's
(leka/admin/activity.py). docs/data-lifecycle.md lists every one.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import and_, delete, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin import audit
from leka.admin.models import AdminAuditEvent, AdminCode, AdminSession
from leka.core.config import settings
from leka.db import session_factory, system_scope

logger = structlog.get_logger(__name__)

SESSIONS_KEPT = timedelta(days=30)
CODES_KEPT = timedelta(days=7)
# alembic/versions/20261118_0900_leka_admin_security.py makes them.
TRIGGERS = ("admin_audit_events_append_only", "admin_audit_events_never_emptied")


async def unprotected(session: AsyncSession) -> list[str]:
    """The trail's triggers that are missing or disabled; none when it is
    protected."""
    enabled = set(
        (
            await session.scalars(
                text(
                    "SELECT tgname FROM pg_trigger WHERE tgrelid = 'admin_audit_events'::regclass"
                    " AND NOT tgisinternal AND tgenabled <> 'D'"
                )
            )
        ).all()
    )
    return [name for name in TRIGGERS if name not in enabled]


async def _sweep_trail(moment: datetime) -> int:
    days = settings.admin_audit_retention_days
    before = moment - timedelta(days=days)
    async with session_factory() as session:
        missing = await unprotected(session)
        if missing:
            logger.error("admin_trail_unprotected", missing=missing)
            audit.record(
                session,
                "admin.trail_unprotected",
                admin_id=None,
                outcome="failed",
                target_type="admin_audit_events",
                detail={"missing": missing},
            )
            await session.commit()
            return 0
        # The trigger lets this transaction, and no other, delete.
        await session.execute(text("SET LOCAL leka.admin_audit_sweep = 'on'"))
        result = await session.execute(delete(AdminAuditEvent).where(AdminAuditEvent.at < before))
        count = int(getattr(result, "rowcount", 0) or 0)
        if count:
            audit.record(
                session,
                "admin.trail_expired",
                admin_id=None,
                target_type="admin_audit_events",
                detail={"count": count, "before": before.isoformat(), "days": days},
            )
        await session.commit()
        return count


async def sweep(*, now: datetime | None = None) -> dict[str, int]:
    """What is past its keeping, deleted; how many of each. Idempotent: run
    again, nothing more is old enough."""
    moment = now or datetime.now(UTC)
    with system_scope():
        trail = await _sweep_trail(moment)
        async with session_factory() as session:
            ended = moment - SESSIONS_KEPT
            sessions = await session.execute(
                delete(AdminSession).where(
                    or_(
                        and_(AdminSession.revoked_at.is_not(None), AdminSession.revoked_at < ended),
                        AdminSession.expires_at < ended,
                    )
                )
            )
            spent = moment - CODES_KEPT
            codes = await session.execute(
                delete(AdminCode).where(
                    or_(
                        and_(AdminCode.consumed_at.is_not(None), AdminCode.consumed_at < spent),
                        AdminCode.expires_at < spent,
                    )
                )
            )
            await session.commit()
    swept = {
        "trail": trail,
        "sessions": int(getattr(sessions, "rowcount", 0) or 0),
        "codes": int(getattr(codes, "rowcount", 0) or 0),
    }
    logger.info("admin_retention_swept", **swept)
    return swept


def run_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(sweep())
