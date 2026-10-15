"""A workspace may be a demonstration.

Revision ID: 9b3e5d7c1a42
Revises: 6e1c9a4b7d20
Created: 2026-10-23

LEKA-449:
- `workspaces.demo`: a demonstration — fictive data its own connectors
  replay, nothing of a customer's, nothing that reaches a real system. Set
  when LEKA makes it; every workspace that exists is not one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9b3e5d7c1a42"
down_revision: str | None = "6e1c9a4b7d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces", sa.Column("demo", sa.Boolean(), server_default="false", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("workspaces", "demo")
