"""What a call cost LEKA (LEKA-430): priced with the rates kept in the
database (model_rates) — configurable, dated, never rewritten — the one in
force the day of the call, its id kept with the call so that its cost can
be read again. profiles.py's list prices are what the table was seeded
with; routing still reads them, as it did.

A model without a rate costs what is not known: None, never 0. A call whose
provider did not say what it used is not priced either — 0 tokens read is
not 0 tokens used.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.gateway.contract import Usage
from leka.capabilities.gateway.profiles import Price, cost_at
from leka.capabilities.models import ModelRate


@dataclass(frozen=True)
class Rate:
    id: uuid.UUID
    provider: str
    model: str
    price: Price

    @classmethod
    def of(cls, row: ModelRate) -> Rate:
        return cls(
            row.id,
            row.provider,
            row.model,
            Price(row.since, row.per_million_in, row.per_million_out, row.per_million_cached),
        )

    def cost(self, usage: Usage) -> float:
        return cost_at(self.price, usage.tokens_in, usage.tokens_out, cached=usage.tokens_cached)


class Rates:
    """Every rate, by model: the one in force on a day."""

    def __init__(self, rates: Iterable[Rate]) -> None:
        self._by_model: dict[tuple[str, str], list[Rate]] = defaultdict(list)
        for rate in rates:
            self._by_model[(rate.provider, rate.model)].append(rate)
        for found in self._by_model.values():
            found.sort(key=lambda r: r.price.since)

    def at(self, provider: str, model: str, when: datetime) -> Rate | None:
        day = when.date()
        current = [r for r in self._by_model.get((provider, model), ()) if r.price.since <= day]
        return current[-1] if current else None


async def load_rates(session: AsyncSession) -> Rates:
    """Every rate — a table of a few rows a model."""
    return Rates(Rate.of(row) for row in (await session.scalars(select(ModelRate))).all())
