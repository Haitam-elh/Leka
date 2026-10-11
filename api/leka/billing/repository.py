"""Every query of the billing module (LEKA-431): the pricing page's events."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing.models import SiteEvent


class SiteEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, event: SiteEvent) -> None:
        self._session.add(event)

    async def counts(self, *, since: datetime) -> list[tuple[str, str | None, str | None, int]]:
        rows = await self._session.execute(
            select(SiteEvent.event, SiteEvent.plan, SiteEvent.interval, func.count())
            .where(SiteEvent.at >= since)
            .group_by(SiteEvent.event, SiteEvent.plan, SiteEvent.interval)
            .order_by(SiteEvent.event, SiteEvent.plan, SiteEvent.interval)
        )
        return [(e, p, i, int(n)) for e, p, i, n in rows.all()]
