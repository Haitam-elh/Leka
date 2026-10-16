"""The notification centre as one person reads it (LEKA-476).

What they see: the notifications of their workspace whose audience is them
— by their id, by a permission they hold now, or every member — less the
categories they muted, less what is about an entity hidden from them. The
latest first, a page at a time; read or not, as they left it.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, delete, func, literal, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from leka.governance import Principal
from leka.notifications.models import (
    CATEGORIES,
    Notification,
    NotificationPreference,
    NotificationSeen,
)
from leka.notifications.schemas import NotificationOut, NotificationPage


class CursorError(ValueError):
    """A page's cursor that is not one this list gave."""


def _cursor(at: datetime, notification_id: uuid.UUID) -> str:
    raw = f"{at.isoformat()}|{notification_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _uncursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        at, ident = raw.split("|", 1)
        return datetime.fromisoformat(at), uuid.UUID(ident)
    except (ValueError, UnicodeDecodeError) as error:
        raise CursorError(cursor) from error


class Notifications:
    """One person's notifications, in their workspace."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._session = session
        self._principal = principal

    def _visible(self) -> ColumnElement[bool]:
        """Theirs: them by name, a permission they hold, or every member."""
        held = sorted(str(p.value) for p in self._principal.permissions)
        return or_(
            Notification.audience_user_id == self._principal.user_id,
            Notification.audience_permission.in_(held),
            and_(
                Notification.audience_user_id.is_(None),
                Notification.audience_permission.is_(None),
            ),
        )

    def _read_by_them(self) -> ColumnElement[bool]:
        # Its own alias: the list joins the reads too, and would otherwise
        # take this one for that one.
        seen = aliased(NotificationSeen)
        return (
            select(seen.id)
            .where(seen.notification_id == Notification.id, seen.user_id == self._principal.user_id)
            .correlate(Notification)
            .exists()
        )

    async def muted(self) -> list[str]:
        row = await self._session.scalar(
            select(NotificationPreference).where(
                NotificationPreference.user_id == self._principal.user_id
            )
        )
        return [c for c in (row.muted if row else []) if c in CATEGORIES]

    async def _shown(self, category: str | None) -> list[ColumnElement[bool]]:
        clauses = [self._visible()]
        muted = await self.muted()
        if muted:
            clauses.append(Notification.category.notin_(muted))
        if category is not None:
            clauses.append(Notification.category == category)
        return clauses

    async def unread(self) -> int:
        clauses = await self._shown(None)
        found = await self._session.scalar(
            select(func.count()).select_from(Notification).where(*clauses, ~self._read_by_them())
        )
        return int(found or 0)

    async def page(
        self, *, category: str | None, unread: bool, cursor: str | None, limit: int
    ) -> NotificationPage:
        clauses = await self._shown(category)
        if unread:
            clauses.append(~self._read_by_them())
        if cursor:
            at, ident = _uncursor(cursor)
            clauses.append(
                tuple_(Notification.occurred_at, Notification.id)
                < tuple_(literal(at), literal(ident))
            )
        rows = (
            await self._session.execute(
                select(Notification, NotificationSeen.read_at)
                .outerjoin(
                    NotificationSeen,
                    and_(
                        NotificationSeen.notification_id == Notification.id,
                        NotificationSeen.user_id == self._principal.user_id,
                    ),
                )
                .where(*clauses)
                .order_by(Notification.occurred_at.desc(), Notification.id.desc())
                .limit(limit + 1)
            )
        ).all()
        more = len(rows) > limit
        shown = rows[:limit]
        last = shown[-1][0] if shown else None
        return NotificationPage(
            data=[
                NotificationOut(
                    id=n.id,
                    category=n.category,
                    kind=n.kind,
                    severity=n.severity,
                    params=n.params,
                    link=n.link,
                    occurred_at=n.occurred_at,
                    read=read_at is not None,
                )
                for n, read_at in shown
            ],
            next_cursor=_cursor(last.occurred_at, last.id) if more and last else None,
            unread=await self.unread(),
        )

    async def _theirs(self, notification_id: uuid.UUID) -> bool:
        found = await self._session.scalar(
            select(Notification.id).where(Notification.id == notification_id, self._visible())
        )
        return found is not None

    async def mark(self, notification_id: uuid.UUID, *, read: bool) -> bool:
        """Read, or unread again. False: not one of theirs."""
        if not await self._theirs(notification_id):
            return False
        if read:
            await self._session.execute(
                insert(NotificationSeen)
                .values(
                    id=uuid.uuid4(),
                    workspace_id=self._principal.workspace_id,
                    notification_id=notification_id,
                    user_id=self._principal.user_id,
                    read_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="uq_notification_reads_person")
            )
        else:
            await self._session.execute(
                delete(NotificationSeen).where(
                    NotificationSeen.notification_id == notification_id,
                    NotificationSeen.user_id == self._principal.user_id,
                )
            )
        return True

    async def mark_all(self, *, category: str | None) -> int:
        """Every one shown to them, unread, read now — of a category, or all."""
        clauses = await self._shown(category)
        ids = list(
            (
                await self._session.scalars(
                    select(Notification.id).where(*clauses, ~self._read_by_them())
                )
            ).all()
        )
        if not ids:
            return 0
        now = datetime.now(UTC)
        await self._session.execute(
            insert(NotificationSeen)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "workspace_id": self._principal.workspace_id,
                        "notification_id": ident,
                        "user_id": self._principal.user_id,
                        "read_at": now,
                    }
                    for ident in ids
                ]
            )
            .on_conflict_do_nothing(constraint="uq_notification_reads_person")
        )
        return len(ids)

    async def set_muted(self, muted: list[str]) -> list[str]:
        """What they do not want told here, by category."""
        kept = sorted({c for c in muted if c in CATEGORIES})
        await self._session.execute(
            insert(NotificationPreference)
            .values(
                id=uuid.uuid4(),
                workspace_id=self._principal.workspace_id,
                user_id=self._principal.user_id,
                muted=kept,
            )
            .on_conflict_do_update(
                constraint="uq_notification_preferences_person", set_={"muted": kept}
            )
        )
        return kept
