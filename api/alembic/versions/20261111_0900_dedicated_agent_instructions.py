"""A dedicated agent's own instructions (2026-10-25): an organisation's
architect follows its organisation's words — kept with the agent dedicated
to it, never in LEKA's code.

Revision ID: 7c1e5b3a9d20
Revises: 4f7a2c9d1b63
Created: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c1e5b3a9d20"
down_revision: str | None = "4f7a2c9d1b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dedicated_agents", sa.Column("instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("dedicated_agents", "instructions")
