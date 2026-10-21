"""GPT-6's list prices as rates, from developers.openai.com/api/docs/pricing,
read 2026-10-21 — as profiles.py says them, so every call's cost is known.

Revision ID: 2475a6dde8de
Revises: 2931d1880b8c
Created: 2026-10-21
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa

from alembic import op

revision: str = "2475a6dde8de"
down_revision: str | None = "2931d1880b8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RATES = [
    ("openai", "gpt-6-astra", 10.0, 50.0, 1.0),
    ("openai", "gpt-6.1-sol", 2.0, 10.0, 0.1),
    ("openai", "gpt-6-luna", 0.1, 0.5, 0.01),
]
SOURCE = "list price, developers.openai.com/api/docs/pricing"

rates = sa.table(
    "model_rates",
    sa.column("id", sa.UUID()),
    sa.column("provider", sa.String()),
    sa.column("model", sa.String()),
    sa.column("since", sa.Date()),
    sa.column("per_million_in", sa.Float()),
    sa.column("per_million_out", sa.Float()),
    sa.column("per_million_cached", sa.Float()),
    sa.column("source", sa.String()),
)


def upgrade() -> None:
    op.bulk_insert(
        rates,
        [
            {
                "id": uuid.uuid4(),
                "provider": provider,
                "model": model,
                "since": date(2025, 1, 1),
                "per_million_in": per_in,
                "per_million_out": per_out,
                "per_million_cached": cached,
                "source": SOURCE,
            }
            for provider, model, per_in, per_out, cached in RATES
        ],
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM model_rates WHERE model IN ('gpt-6-astra', 'gpt-6.1-sol', 'gpt-6-luna') "
        "AND id NOT IN (SELECT rate_id FROM model_calls WHERE rate_id IS NOT NULL)"
    )
