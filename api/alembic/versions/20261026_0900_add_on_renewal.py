"""An agent's or a bundle's subscription, cancelled at its period's end or
renewed (LEKA-474): said on what it grants.

Revision ID: 5c2e9a7f1b44
Revises: 8a4c1e7b2d95
Create Date: 2026-10-16 23:50:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5c2e9a7f1b44"
down_revision: str | None = "8a4c1e7b2d95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_entitlements",
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "agent_entitlements",
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_entitlements", "current_period_end")
    op.drop_column("agent_entitlements", "cancel_at_period_end")
