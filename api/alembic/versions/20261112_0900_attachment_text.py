"""What a file joined to an intention says (2026-10-28): its text, read once
— PDF, OCR, Office — kept with it for every model that reads it after.

Revision ID: 9b2e4d7f1a35
Revises: 7c1e5b3a9d20
Created: 2026-10-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9b2e4d7f1a35"
down_revision: str | None = "7c1e5b3a9d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("intention_attachments", sa.Column("text", sa.Text(), nullable=True))
    op.add_column("intention_attachments", sa.Column("read_as", sa.String(20), nullable=True))
    op.add_column("intention_attachments", sa.Column("read_why", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("intention_attachments", "read_why")
    op.drop_column("intention_attachments", "read_as")
    op.drop_column("intention_attachments", "text")
