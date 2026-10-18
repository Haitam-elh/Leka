"""An intention's deletion asked while something still worked on it
(LEKA-487): out of every list until the sweep deletes it.

Revision ID: 1edec9bb485e
Revises: bb4d53f55a47
Created: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1edec9bb485e"
down_revision: str | None = "bb4d53f55a47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "intentions", sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("intentions", "deletion_requested_at")
