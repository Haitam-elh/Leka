"""Source settings: a retention of their own.

Revision ID: 4d7e2a9c1b63
Revises: 8f1c6b3e5d27
Created: 2026-09-28

LEKA-348. A source's settings gain `retention` — {"days": 14}, or {} for
LEKA's policy for its kind. A source may keep its raw payloads less long
than the policy, never longer: the sync writes each payload's expiry with
the shorter of the two (leka/ingestion/retention.py). Every version saved
before has none: the policy, as before.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4d7e2a9c1b63"
down_revision: str | None = "8f1c6b3e5d27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_settings",
        sa.Column(
            "retention",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("source_settings", "retention")
