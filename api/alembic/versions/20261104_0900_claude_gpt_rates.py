"""Claude 5.5's and GPT-5.6's list prices as rates: what each costs LEKA per
million tokens, from platform.claude.com/docs/en/about-claude/pricing and
developers.openai.com/api/docs/pricing, read 2026-10-20 — as profiles.py
says them, so every call's cost is known.

Revision ID: 5c5784f08f2c
Revises: 5e1f9a3c7b20
Created: 2026-10-20
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa

from alembic import op

revision: str = "5c5784f08f2c"
down_revision: str | None = "5e1f9a3c7b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RATES = [
    ("anthropic", "claude-opus-5-5", 4.0, 20.0, 0.2),
    ("anthropic", "claude-sonnet-5-5", 2.0, 10.0, 0.1),
    # Up to 100,000 tokens read: five times more beyond.
    ("anthropic", "claude-haiku-5-5", 0.1, 0.5, 0.01),
    ("openai", "gpt-5.6-sol", 4.0, 20.0, 0.4),
    ("openai", "gpt-5.6-luna", 0.2, 1.2, 0.02),
]
SOURCE = "list price, platform.claude.com and developers.openai.com"

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
        "DELETE FROM model_rates WHERE model IN ("
        "'claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5', "
        "'gpt-5.6-sol', 'gpt-5.6-luna') "
        "AND id NOT IN (SELECT rate_id FROM model_calls WHERE rate_id IS NOT NULL)"
    )
