"""The interface in every language (2026-10-30): the words LEKA's model
translated, one row a language, LEKA's and no customer's.

Revision ID: 3d7a1f9c5e62
Revises: 5e8c2a7f4b19
Created: 2026-10-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3d7a1f9c5e62"
down_revision: str | None = "5e8c2a7f4b19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interface_words",
        sa.Column("tag", sa.String(length=35), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column(
            "words", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "failed", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('translating', 'ready', 'failed')",
            name=op.f("ck_interface_words_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interface_words")),
        sa.UniqueConstraint("tag", name="uq_interface_words_tag"),
    )


def downgrade() -> None:
    op.drop_table("interface_words")
