"""A code change's pull request, followed after it was opened — read only:
its checks, a person's merge, the deployment that took it.

Revision ID: 5e1f9a3c7b20
Revises: c184793fb3fb
Created: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5e1f9a3c7b20"
down_revision: str | None = "c184793fb3fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "code_changes",
        sa.Column("follow", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("code_changes", "follow")
