"""Context ranking: how each version and each element was ranked.

Revision ID: 3b8e5a7c1d42
Revises: f6f99d6d6f4a
Created: 2026-10-05

LEKA-372. A version says how it was ranked — the policy, what was left
out and why (a duplicate, too little relevant, beyond the budget), what
its sources disagree on (`context_versions.ranking`); each element, its
score, its place and every signal it was read from
(`context_elements.ranking`). The versions made before hold none: they
were ordered by relevance alone, and say so by saying nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3b8e5a7c1d42"
down_revision: str | None = "f6f99d6d6f4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "context_versions",
        sa.Column("ranking", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "context_elements",
        sa.Column("ranking", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("context_elements", "ranking")
    op.drop_column("context_versions", "ranking")
