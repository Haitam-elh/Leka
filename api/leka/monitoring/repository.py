"""What the watch keeps (LEKA-442): a workspace's alerts — those open, and
those ended lately."""

from __future__ import annotations

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
