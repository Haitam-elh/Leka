"""OpenAI's list prices as rates (LEKA-491): what GPT-4.1 and its mini cost
LEKA per million tokens, from openai.com/api/pricing — as profiles.py says
them, so every call's cost is known.

Revision ID: 4c8e2a6f9b13
Revises: d1dd03b07ab2
Created: 2026-10-18
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa

from alembic import op

revision: str = "4c8e2a6f9b13"
down_revision: str | None = "d1dd03b07ab2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RATES = [
    ("openai", "gpt-4.1", 2.0, 8.0, 0.5),
    ("openai", "gpt-4.1-mini", 0.4, 1.6, 0.1),
]
SOURCE = "list price, openai.com/api/pricing"

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
        "DELETE FROM model_rates WHERE provider = 'openai' "
        "AND model IN ('gpt-4.1', 'gpt-4.1-mini') "
        "AND id NOT IN (SELECT rate_id FROM model_calls WHERE rate_id IS NOT NULL)"
    )
