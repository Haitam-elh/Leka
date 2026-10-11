"""Languages: the one a person chose and their region; a workspace's own.

Revision ID: 5d8a1c3e7f29
Revises: 7c2e9f4a1b85
Created: 2026-10-19

`users.language` and `users.region`: what a person chose (a tag of
leka/core/languages.yaml, an ISO 3166-1 country), NULL until they choose.
`workspaces.default_language`: the language of what is shared in it.

Every workspace that exists was made in a French product, and keeps
speaking French; a new one takes its creator's language, English when
nobody said one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5d8a1c3e7f29"
down_revision: str | None = "7c2e9f4a1b85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("language", sa.String(length=35), nullable=True))
    op.add_column("users", sa.Column("region", sa.String(length=2), nullable=True))
    op.add_column(
        "workspaces",
        sa.Column("default_language", sa.String(length=35), nullable=True),
    )
    op.execute("UPDATE workspaces SET default_language = 'fr'")
    op.alter_column(
        "workspaces", "default_language", nullable=False, server_default=sa.text("'en'")
    )


def downgrade() -> None:
    op.drop_column("workspaces", "default_language")
    op.drop_column("users", "region")
    op.drop_column("users", "language")
