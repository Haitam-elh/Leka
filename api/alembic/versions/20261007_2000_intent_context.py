"""Intent context: whether an intention's context can ground its analysis.

Revision ID: 8b4f1d6a2c97
Revises: 6d2a9f4c8e13
Created: 2026-10-07

LEKA-387. Each intention keeps whether its context — assembled from its
scope — can ground its analysis (`intentions.readiness`): ready, limited,
blocked, and the critical gaps and conflicts in the way.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8b4f1d6a2c97"
down_revision: str | None = "6d2a9f4c8e13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "intentions",
        sa.Column("readiness", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("intentions", "readiness")
