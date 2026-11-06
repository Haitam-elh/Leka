"""Filling the seam LEKA-331 left open.

leka.platform.seam declares two dependencies that raise until somebody
implements them. This module implements them and registers the
implementations, without changing a line of leka.platform or
leka.governance — which was the point of designing the seam that way.

The registration goes through app.dependency_overrides. That mechanism is
usually a testing tool, and using it as production wiring is the one place
where the seam's shape shows. It works because FastAPI resolves overrides on
every request exactly as it resolves the original. The alternative — a
registry inside seam.py — would mean editing leka.platform, which this
ticket may not do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.attributes import set_committed_value

from leka.core.config import settings
from leka.core.security import hash_token
from leka.db import DatabaseSession, session_factory
from leka.identity.models import Session
from leka.identity.repository import SessionRepository
from leka.platform import (
    UserId,
    WorkspaceId,
    get_current_user_id,
    get_session_store,
)

logger = structlog.get_logger(__name__)

SessionDep = DatabaseSession

# The idle clock, refreshed once a minute at most and in a transaction of its
# own, committed at once. Written in the request's own transaction, the row
# stayed locked until the request ended: on 2026-11-06 one slow search held
# it for minutes, every other request of the same person queued behind it,
# and the API ran out of connections (503 everywhere).
TOUCH_EVERY = timedelta(minutes=1)


async def touch(session: Session, now: datetime) -> None:
    """`last_seen_at` moved to now, never waiting on a lock: a row someone
    else holds is left for the next request."""
    try:
        async with session_factory() as own:
            await own.execute(text("SET LOCAL lock_timeout = '1s'"))
            await own.execute(
                update(Session).where(Session.id == session.id).values(last_seen_at=now)
            )
            await own.commit()
    except DBAPIError:
        logger.warning("session_touch_skipped", session_id=str(session.id))
        return
    # Known as written, so the request's transaction never writes it again.
    set_committed_value(session, "last_seen_at", now)


def read_session_token(request: Request) -> str | None:
    """The raw token from the cookie, if there is one."""
    return request.cookies.get(settings.session_cookie_name)


async def load_session(request: Request, db: SessionDep) -> Session | None:
    """The live session this request belongs to, or None.

    One dependency, resolved once per request: FastAPI caches the result, so
    both seam implementations read the same row without a second query.

    "Live" means all four conditions — present, not revoked, inside the
    absolute expiry, and inside the idle window. A session that fails any of
    them is treated as absent, and the idle clock is refreshed on the way
    through so that active use keeps a session alive.
    """
    token = read_session_token(request)
    if token is None:
        return None

    sessions = SessionRepository(db)
    session = await sessions.get_live_by_token_hash(hash_token(token))
    if session is None:
        return None

    now = datetime.now(UTC)
    if session.expires_at <= now:
        return None

    idle_deadline = session.last_seen_at + timedelta(days=settings.session_idle_lifetime_days)
    if idle_deadline <= now:
        # Idle too long. Revoked rather than merely ignored, so the row does
        # not sit there looking usable.
        await sessions.revoke(session)
        return None

    if now - session.last_seen_at >= TOUCH_EVERY:
        await touch(session, now)
    return session


async def current_user_id(
    session: Annotated[Session | None, Depends(load_session)],
) -> UserId:
    """Implements leka.platform.seam.get_current_user_id.

    Raises an HTTPException rather than SeamNotImplementedError when there is
    no session. The seam's placeholder raised the latter because "nobody has
    implemented this" is a programming error; "you are not signed in" is an
    ordinary outcome of an ordinary request, and must be a 401.

    An early version of this module kept the placeholder's exception, and
    every LEKA-331 route answered an unauthenticated visitor with a 500.
    """
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "You are not signed in.", "code": "not_authenticated"},
        )
    return UserId(session.user_id)


class DatabaseSessionStore:
    """Implements leka.platform.seam.SessionStore.

    The active workspace lives in a column of the session row, server side.
    That is what makes architecture rule 3 true in practice: there is nowhere
    for a client to put a workspace, because the server reads it from its own
    storage.
    """

    def __init__(self, session: Session | None) -> None:
        self._session = session

    async def get_active_workspace(self, request: Request) -> WorkspaceId | None:
        if self._session is None or self._session.active_workspace_id is None:
            return None
        return WorkspaceId(self._session.active_workspace_id)

    async def set_active_workspace(self, request: Request, workspace_id: WorkspaceId) -> None:
        """Move this browser to another workspace.

        Called only by LEKA-331's switch route, which verifies a membership
        first. Writing to the session row rather than to a cookie means the
        change survives nothing the client controls.
        """
        if self._session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "detail": "You are not signed in.",
                    "code": "not_authenticated",
                },
            )
        self._session.active_workspace_id = workspace_id


async def session_store(
    session: Annotated[Session | None, Depends(load_session)],
) -> DatabaseSessionStore:
    return DatabaseSessionStore(session)


def configure_identity(app: FastAPI) -> None:
    """Plug the real implementations into the seam.

    Called once from leka.main. Tests replace these with their own overrides
    exactly as they did before LEKA-330 existed, which is how the LEKA-331
    suite keeps working unchanged.
    """
    app.dependency_overrides[get_current_user_id] = current_user_id
    app.dependency_overrides[get_session_store] = session_store
    logger.info("identity_seam_wired")
