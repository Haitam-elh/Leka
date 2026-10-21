"""Mistral's list prices as rates, from docs.mistral.ai/inference/pricing,
read 2026-10-21: Medium and Small had none — their cost was not known — and
Large's cached tokens had no price of their own. As profiles.py says them.

Revision ID: 2931d1880b8c
Revises: 3c7e1a9d5f24
Created: 2026-10-21
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa

from alembic import op

revision: str = "2931d1880b8c"
down_revision: str | None = "3c7e1a9d5f24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SINCE = date(2026, 10, 21)
RATES = [
    ("mistral", "mistral-large-latest", 0.5, 1.5, 0.05),
    ("mistral", "mistral-medium-latest", 1.5, 7.5, 0.15),
    ("mistral", "mistral-small-latest", 0.15, 0.6, 0.015),
]
SOURCE = "list price, docs.mistral.ai/inference/pricing"

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
                "since": SINCE,
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
        "DELETE FROM model_rates WHERE provider = 'mistral' AND since = '2026-10-21' "
        "AND id NOT IN (SELECT rate_id FROM model_calls WHERE rate_id IS NOT NULL)"
    )
