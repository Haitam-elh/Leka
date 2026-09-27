"""Normalised records remember the settings version they were mapped with.

Revision ID: 8f1c6b3e5d27
Revises: 5a3d8e2f9c41
Created: 2026-09-28

LEKA-351. One column on `normalised_records`: `settings_version`, the version
of the source's settings whose mapping made the row (0 before any). A new
mapping makes the source's rows stale, and normalisation makes them again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f1c6b3e5d27"
down_revision: str | None = "5a3d8e2f9c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "normalised_records",
        sa.Column("settings_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("normalised_records", "settings_version")
