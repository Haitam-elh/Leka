"""An intention's answers: what its asker answered to LEKA's questions.

Revision ID: 8b3f1d6a2c47
Revises: 5d8a1c3e7f29
Created: 2026-10-20

`intentions.answers` (LEKA-439): one per question — a choice, their own
words, or « je ne sais pas » — read again with the intention every time it
is understood. Every intention that exists was asked nothing: an empty list.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8b3f1d6a2c47"
down_revision: str | None = "5d8a1c3e7f29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "intentions",
        sa.Column("answers", postgresql.JSONB(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("intentions", "answers")
