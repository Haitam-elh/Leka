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
which organisation, the outcome, when, the route, the request id, the
session it was done in, the address's prefix — and a small detail, never
the data that was read.

What can be said is ACTIONS (LEKA-546): an action it does not list is a
mistake in the code, refused here rather than kept under a name nobody
reads. tests/test_admin_security.py holds that every one the code records is
there.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.models import AdminAuditEvent
from leka.core.request_context import current_request_id
from leka.db import session_factory

logger = structlog.get_logger(__name__)

ACTIONS: dict[str, str] = {
    # Signing in and the sessions.
    "admin.signed_in": "signed in: a new session",
    "admin.sign_in_failed": "a sign-in refused, with its reason",
    "admin.signed_out": "signed out of this session",
    "admin.session_renewed": "a session renewed: a new token, the same end",
    "admin.session_ended": "one of the admin's own sessions closed, from another",
    "admin.session_reused": "an ended token shown again: its device's sessions ended",
    "admin.signed_out_everywhere": "every session of an admin closed by a Super Admin",
    # Passwords and codes.
    "admin.password_reset_asked": "a code asked for a forgotten password",
    "admin.code_refused": "a code that is not one, or no longer",
    "admin.password_set": "a password chosen with a code",
    "admin.password_changed": "a password changed while signed in",
    "admin.password_change_refused": "a password change refused",
    # Reading.
    "admin.refused": "a route refused: the role does not grant it",
    "admin.viewed": "an organisation, a person or an intention read",
    "admin.viewed_content": "what a customer wrote or an agent delivered, read",
    "admin.viewed_trail": "this trail read",
    # Changing a customer.
    "admin.organisation_suspended": "an organisation suspended, with the reason",
    "admin.organisation_reactivated": "an organisation reactivated, with the reason",
    "admin.credits_added": "credits added to an organisation's month, with the reason",
    "admin.credits_adjusted": (
        "credits given back or adjusted in an organisation's ledger, with the reason"
    ),
    "admin.organisation_updated": "an organisation's name, country or size changed (LEKA-549)",
    "admin.note_added": "an internal note written about an organisation: never its words",
    # The team.
    "admin.account_created": "an admin account created from the server",
    "admin.invited": "an admin invited",
    "admin.invitation_sent": "an invitation sent again",
    "admin.account_changed": "an admin's name, role or access changed",
    "admin.role_changed": "what a role may do changed",
    # The trail itself.
    "admin.trail_expired": "rows past the retention deleted by the nightly sweep",
    "admin.trail_unprotected": "the database's protection of this trail found missing",
}

# The admin session the request is served in, set once its token is
# resolved (leka/admin/dependencies.py): each row says which device did it.
_acting_session: ContextVar[uuid.UUID | None] = ContextVar(
    "leka_admin_acting_session", default=None
)


@contextmanager
def acting_in(session_id: uuid.UUID) -> Iterator[None]:
    token = _acting_session.set(session_id)
    try:
        yield
    finally:
        _acting_session.reset(token)


def _known(action: str) -> str:
    if action not in ACTIONS:
        raise ValueError(f"{action!r} is not an action of the admin trail (audit.ACTIONS).")
    return action


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
    session_id: uuid.UUID | None = None,
) -> AdminAuditEvent:
    return AdminAuditEvent(
        id=uuid.uuid4(),
        at=datetime.now(UTC),
        admin_id=admin_id,
        admin_email=admin_email,
        action=_known(action),
        outcome=outcome,
        target_type=target_type,
        target_id=target_id,
        for_workspace_id=workspace_id,
        route=(route or "")[:200] or None,
        request_id=current_request_id(),
        ip_prefix=ip_prefix,
        session_id=session_id or _acting_session.get(),
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
    session_id: uuid.UUID | None = None,
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
            session_id=session_id,
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
    session_id: uuid.UUID | None = None,
) -> None:
    """Kept on its own, committed now. Refusing stays refusing: a trail that
    cannot be written is logged, never a reason to let the request through."""
    _known(action)
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
                    session_id=session_id,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("admin_audit_unrecorded", action=action)
