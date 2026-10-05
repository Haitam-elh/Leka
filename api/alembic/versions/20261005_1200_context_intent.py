"""Context intent: the intention a context was assembled for.

Revision ID: 9d2f4c6a8b10
Revises: 3b8e5a7c1d42
Created: 2026-10-05

LEKA-373. A context assembled for an intention keeps how LEKA read it —
its kind, what it is about, when, where, under what constraints, the
context request it made, what was missing (`contexts.intent`). A context
asked for directly, and those made before, hold none.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9d2f4c6a8b10"
down_revision: str | None = "3b8e5a7c1d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "contexts",
        sa.Column("intent", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contexts", "intent")
