"""A code change undone (2026-10-20): the change that undoes another, and
each time a person went back to the version before it.

Revision ID: 8b4d2f6a1c93
Revises: 5c5784f08f2c
Created: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8b4d2f6a1c93"
down_revision: str | None = "5c5784f08f2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("code_changes", sa.Column("reverts", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_code_changes_reverts_code_changes",
        "code_changes",
        "code_changes",
        ["reverts"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "code_changes",
        sa.Column(
            "rollbacks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("code_changes", "rollbacks")
    op.drop_constraint("fk_code_changes_reverts_code_changes", "code_changes", type_="foreignkey")
    op.drop_column("code_changes", "reverts")
