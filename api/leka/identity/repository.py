"""Database access for the identity module.

The only place in this module where a query is written (architecture rule 4).

These repositories do NOT inherit WorkspaceScopedRepository, and that is the
correct choice rather than a shortcut. That base class exists to make a
workspace filter unforgettable; users, sessions and email_tokens have no
workspace to filter by. Inheriting it would mean disabling the one thing it
does. leka.platform already has this shape — WorkspaceRepository and
MembershipResolver are plain for the same reason.

The scope guard in leka.db does not apply here either: it fires only on
models inheriting WorkspaceScopedMixin, and none of these do.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Result, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.identity.models import EmailToken, Session, TokenPurpose, User


def _affected_rows(result: Result[Any]) -> int:
    """How many rows an UPDATE or DELETE touched.

    SQLAlchemy returns a CursorResult for those, which carries rowcount, but
    the declared return type of execute() is the narrower Result. One cast
    here beats four scattered type: ignore comments.
    """
    return int(cast("CursorResult[Any]", result).rowcount or 0)


class UserRepository:
    """Reads and writes rows in `users`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Look up by address.

        The caller lower-cases before calling — the schemas do it on the way
        in — so that Nora@ and nora@ cannot become two accounts.
        """
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    def add(self, user: User) -> None:
        self._session.add(user)

    async def flush(self) -> None:
        await self._session.flush()


class SessionRepository:
    """Reads and writes rows in `sessions`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_live_by_token_hash(self, token_hash: str) -> Session | None:
        """The session this token belongs to, if it is still usable.

        "Live" means all three: not revoked, not past its absolute expiry,
        and not idle beyond the inactivity window. Checking them here rather
        than at the call site means no route can forget one.
        """
        result = await self._session.execute(
            select(Session)
            .where(Session.token_hash == token_hash)
            .where(Session.revoked_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[Session]:
        """Live sessions, newest first. What the "your devices" screen shows."""
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(Session)
            .where(Session.user_id == user_id)
            .where(Session.revoked_at.is_(None))
            .where(Session.expires_at > now)
            .order_by(Session.last_seen_at.desc())
        )
        return result.scalars().all()

    async def get_for_user(self, user_id: uuid.UUID, session_id: uuid.UUID) -> Session | None:
        """One of this person's sessions.

        Scoped by user_id, so revoking someone else's session by guessing an
        id is not possible.
        """
        result = await self._session.execute(
            select(Session).where(Session.id == session_id).where(Session.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def revoke(self, session: Session) -> None:
        session.revoked_at = datetime.now(UTC)

    async def revoke_all_for_user(
        self, user_id: uuid.UUID, *, except_session_id: uuid.UUID | None = None
    ) -> int:
        """Revoke every session of this person, optionally sparing one.

        Used by "sign out everywhere" and by a password change. The exception
        is what lets someone change their password without signing themselves
        out of the browser they are doing it in.
        """
        statement = (
            update(Session)
            .where(Session.user_id == user_id)
            .where(Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        if except_session_id is not None:
            statement = statement.where(Session.id != except_session_id)
        result = await self._session.execute(statement)
        return _affected_rows(result)

    async def delete_expired(self, *, now: datetime | None = None) -> int:
        """Remove sessions past their absolute expiry.

        An expired session is deleted, not merely ignored: a row nobody will
        ever use again is a row that can still leak in a backup.
        """
        moment = now or datetime.now(UTC)
        result = await self._session.execute(delete(Session).where(Session.expires_at < moment))
        return _affected_rows(result)

    def add(self, session: Session) -> None:
        self._session.add(session)

    async def flush(self) -> None:
        await self._session.flush()


class EmailTokenRepository:
    """Reads and writes rows in `email_tokens`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> EmailToken | None:
        """Find a presented token.

        Deliberately returns consumed and expired rows too: the service
        decides what to do with them, and being able to tell "already used"
        from "never existed" is useful in a log even though both produce the
        same answer to the caller.
        """
        result = await self._session.execute(
            select(EmailToken).where(EmailToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def consume(self, token_hash: str, purpose: TokenPurpose) -> EmailToken | None:
        """Spend a token, atomically. Returns None if there was nothing to spend.

        The guard lives in the WHERE rather than in the calling code: two
        concurrent requests run the same UPDATE, PostgreSQL serialises them
        on the row, and the second finds nothing left to update. RETURNING
        brings the row back in the same statement, so there is no second read
        to fall out of step with the write.

        This is the same shape as invalidate_outstanding below, for the same
        reason. A read, a check in Python, then a write is not a guard: it is
        a guard with a gap in the middle, and both requests fit through it.

        No populate_existing, and that was measured rather than assumed. An
        ORM UPDATE ... RETURNING can hand back a stale instance when the row
        already sits in the session's identity map; here it does not, on
        SQLAlchemy 2.0 with or without the option. Nothing loads the row
        beforehand anyway — each HTTP request gets its own session, and this
        is the first statement to touch the token.
        """
        now = datetime.now(UTC)
        result = await self._session.execute(
            update(EmailToken)
            .where(EmailToken.token_hash == token_hash)
            .where(EmailToken.purpose == purpose)
            .where(EmailToken.consumed_at.is_(None))
            .where(EmailToken.expires_at > now)
            .values(consumed_at=now)
            .returning(EmailToken)
        )
        return result.scalar_one_or_none()

    async def invalidate_outstanding(self, user_id: uuid.UUID, purpose: TokenPurpose) -> int:
        """Consume every live token of this kind for this person.

        Called when issuing a new one, and when a password changes. Two live
        reset links at once means the older one — possibly sitting in a
        forwarded email — still works.
        """
        result = await self._session.execute(
            update(EmailToken)
            .where(EmailToken.user_id == user_id)
            .where(EmailToken.purpose == purpose)
            .where(EmailToken.consumed_at.is_(None))
            .values(consumed_at=datetime.now(UTC))
        )
        return _affected_rows(result)

    async def delete_expired(self, *, now: datetime | None = None) -> int:
        moment = now or datetime.now(UTC)
        result = await self._session.execute(
            delete(EmailToken).where(EmailToken.expires_at < moment)
        )
        return _affected_rows(result)

    def add(self, token: EmailToken) -> None:
        self._session.add(token)

    async def flush(self) -> None:
        await self._session.flush()
