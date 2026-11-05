"""What LEKA's team did and read through LEKA ADMIN, kept (LEKA-544, LEKA-546).

Two ways in, as the customers' access decisions have:

`record()`  in the request's transaction: what was done is kept exactly
            when it is done — an organisation suspended and its trail commit
            together, or neither does.
`apart()`   in a transaction of its own, committed now: a refusal or a
            failed sign-in ends the request and rolls it back, and the trail
            of it must not go with it.

What is kept: who (the admin, or the address typed when no account
matched), what (`admin.signed_in`, `admin.viewed_content`…), on what, about
which organisation, the outcome, the route, the request id, the address's
prefix — and a small detail, never the data that was read.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.models import AdminAuditEvent
from leka.core.request_context import current_request_id
from leka.db import session_factory

logger = structlog.get_logger(__name__)


def _row(
    action: str,
    outcome: str,
    *,
    admin_id: uuid.UUID | None,
    admin_email: str | None,
    target_type: str | None,
    target_id: str | None,
    workspace_id: uuid.UUID | None,
    route: str | None,
    ip_prefix: str | None,
    detail: dict[str, object] | None,
) -> AdminAuditEvent:
    return AdminAuditEvent(
        id=uuid.uuid4(),
        at=datetime.now(UTC),
        admin_id=admin_id,
        admin_email=admin_email,
        action=action,
        outcome=outcome,
        target_type=target_type,
        target_id=target_id,
        for_workspace_id=workspace_id,
        route=(route or "")[:200] or None,
        request_id=current_request_id(),
        ip_prefix=ip_prefix,
        detail=detail or {},
    )


def record(
    session: AsyncSession,
    action: str,
    *,
    admin_id: uuid.UUID | None,
    admin_email: str | None = None,
    outcome: str = "succeeded",
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    route: str | None = None,
    ip_prefix: str | None = None,
    detail: dict[str, object] | None = None,
) -> None:
    session.add(
        _row(
            action,
            outcome,
            admin_id=admin_id,
            admin_email=admin_email,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            workspace_id=workspace_id,
            route=route,
            ip_prefix=ip_prefix,
            detail=detail,
        )
    )


async def apart(
    action: str,
    *,
    admin_id: uuid.UUID | None,
    admin_email: str | None = None,
    outcome: str = "refused",
    target_type: str | None = None,
    target_id: str | None = None,
    route: str | None = None,
    ip_prefix: str | None = None,
    detail: dict[str, object] | None = None,
) -> None:
    """Kept on its own, committed now. Refusing stays refusing: a trail that
    cannot be written is logged, never a reason to let the request through."""
    try:
        async with session_factory() as session:
            session.add(
                _row(
                    action,
                    outcome,
                    admin_id=admin_id,
                    admin_email=admin_email,
                    target_type=target_type,
                    target_id=target_id,
                    workspace_id=None,
                    route=route,
                    ip_prefix=ip_prefix,
                    detail=detail,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("admin_audit_unrecorded", action=action)
