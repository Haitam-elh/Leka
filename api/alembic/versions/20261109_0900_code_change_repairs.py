"""A code change's pull request repaired on asking, its checks in red
(2026-10-24): each repair kept.

Revision ID: 9d3c1b7e5a42
Revises: 2475a6dde8de
Created: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9d3c1b7e5a42"
down_revision: str | None = "2475a6dde8de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "code_changes",
        sa.Column(
            "repairs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("code_changes", "repairs")
