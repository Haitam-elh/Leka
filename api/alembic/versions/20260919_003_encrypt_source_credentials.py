"""Store source credentials encrypted, instead of a reference to a secret store.

Revision ID: 003
Revises: 002
Created: 2026-09-19

Migration 001 gave `sources` a `credentials_ref` column: a pointer to an
entry in a secret store. The pointer was there; the store was not, and
nothing in the repository created one. A connector had nowhere to write a
token.

The decision is now recorded in docs/adr/005-credential-storage.md:
credentials are encrypted with Fernet by the application
(leka.platform.secret_box) and the ciphertext is stored here. The key lives
in LEKA_ENCRYPTION_KEYS, in the environment — never in the database, never in
Git.

The old column is dropped rather than migrated. It was never written to: no
connector exists yet, and `sources` holds only demo data.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("sources", "credentials_ref")
    op.add_column(
        "sources",
        sa.Column("credentials_encrypted", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "credentials_encrypted")
    op.add_column(
        "sources",
        sa.Column("credentials_ref", sa.String(length=255), nullable=True),
    )
