"""Rows of the notification centre, for one workspace (LEKA-476)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from leka.db import WorkspaceScopedRepository
from leka.notifications.models import Notification, NotificationCursor


@dataclass(frozen=True)
class Told:
    """One fact to tell: its identity, what it is, how grave, when, its
    words' parts, where it leads — and to whom."""

    key: str
    category: str
    kind: str
    severity: str
    occurred_at: datetime
    params: dict[str, Any] = field(default_factory=dict)
    link: str | None = None
    to_user: uuid.UUID | None = None
    to_permission: str | None = None
    entity_id: uuid.UUID | None = None


class NotificationRepository(WorkspaceScopedRepository):
    """What is told, and how far each family was read."""

    async def keep(self, told: Sequence[Told]) -> int:
        """Kept, each fact once: one already told is left as it is."""
        if not told:
            return 0
        rows = [
            {
                "id": uuid.uuid4(),
                "workspace_id": self.workspace_id,
                "event_key": t.key[:200],
                "category": t.category,
                "kind": t.kind,
                "severity": t.severity,
                "params": {k: v for k, v in t.params.items() if v is not None},
                "link": t.link,
                "audience_user_id": t.to_user,
                "audience_permission": t.to_permission,
                "entity_id": t.entity_id,
                "occurred_at": t.occurred_at,
            }
            for t in told
        ]
        result = await self._session.execute(
            insert(Notification)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_notifications_event")
            .returning(Notification.id)
        )
        return len(result.all())

    async def cursor(self, family: str, *, read_to: datetime) -> NotificationCursor:
        """How far a family was read — from `read_to` the first time."""
        rows = await self._session.scalars(
            self.select(NotificationCursor).where(NotificationCursor.family == family)
        )
        found = rows.first()
        if found is None:
            found = NotificationCursor(
                workspace_id=self.workspace_id, id=uuid.uuid4(), family=family, read_to=read_to
            )
            self.add(found)
            await self._session.flush()
        return found
