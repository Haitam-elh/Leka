"""An alert taken in hand (LEKA-463): by whom, when — the first only.

Revision ID: 8a4c1e7b2d95
Revises: 3f7b2d9e6c18
Create Date: 2026-10-16 04:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8a4c1e7b2d95"
down_revision: str | None = "3f7b2d9e6c18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "monitoring_alerts", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "monitoring_alerts",
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("monitoring_alerts", "acknowledged_by")
    op.drop_column("monitoring_alerts", "acknowledged_at")
