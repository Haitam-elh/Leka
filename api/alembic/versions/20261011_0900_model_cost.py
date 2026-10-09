"""Model calls: the tokens a provider read from its cache; what was asked.

Revision ID: 8b4e2f7a1c93
Revises: 5e2a7c9b1d38
Created: 2026-10-11

Gemini caches the start of a conversation it was sent before — LEKA's
analyst sends its instructions and what it read again at each round of
tools — and bills those tokens a tenth of the others. Kept per call
(`model_calls.tokens_cached`), so what a call cost is what was billed.

What LEKA already asked a model about one thing, for one purpose, and on
which facts (`model_asks`): a background task — a description proposed for
À valider — asks again only once those facts changed, never every hour.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8b4e2f7a1c93"
down_revision: str | None = "5e2a7c9b1d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_calls",
        sa.Column("tokens_cached", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "model_asks",
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("answered", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_model_asks_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_asks")),
        sa.UniqueConstraint("workspace_id", "purpose", "key", name="uq_model_asks_purpose_key"),
    )
    op.create_index(
        op.f("ix_model_asks_workspace_id"), "model_asks", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_model_asks_workspace_id"), table_name="model_asks")
    op.drop_table("model_asks")
    op.drop_column("model_calls", "tokens_cached")
