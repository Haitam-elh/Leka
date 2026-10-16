"""What the watch keeps (LEKA-442): a workspace's alerts — those open, and
those ended lately."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from leka.db import WorkspaceScopedRepository
from leka.monitoring.models import MonitoringAlert


class AlertRepository(WorkspaceScopedRepository):
    """Rows in `monitoring_alerts`, for one workspace."""

    async def open(self) -> Sequence[MonitoringAlert]:
        rows = await self._session.scalars(
            self.select(MonitoringAlert).where(MonitoringAlert.status == "open")
        )
        return list(rows.all())

    async def lately(self, since: datetime, *, limit: int = 200) -> Sequence[MonitoringAlert]:
        """Those open, and those ended since — the latest opened first."""
        rows = await self._session.scalars(
            self.select(MonitoringAlert)
            .where((MonitoringAlert.status == "open") | (MonitoringAlert.resolved_at >= since))
            .order_by(MonitoringAlert.opened_at.desc())
            .limit(limit)
        )
        return list(rows.all())

    async def acknowledge(
        self, alert_id: uuid.UUID, *, by: uuid.UUID, at: datetime
    ) -> MonitoringAlert | None:
        """Taken in hand by someone (LEKA-463) — the first only: acknowledged
        again, it keeps who did first and when. None: no such alert here."""
        row = await self._session.scalar(
            self.select(MonitoringAlert).where(MonitoringAlert.id == alert_id)
        )
        if row is not None and row.acknowledged_at is None:
            row.acknowledged_at = at
            row.acknowledged_by = by
        return row
