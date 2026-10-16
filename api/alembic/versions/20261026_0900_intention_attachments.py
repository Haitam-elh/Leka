"""Files attached to an intention: uploaded before it is asked, linked when
it is — never said attached unless kept.

Revision ID: c7e2a91f4b36
Revises: 5c2e9a7f1b44
Create Date: 2026-10-16 23:00:00

`intention_attachments`: what the store measured of each file (its size,
its checksum), its key there, who uploaded it, and the intention it came
with — none until that intention is asked.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7e2a91f4b36"
down_revision: str | None = "5c2e9a7f1b44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intention_attachments",
        sa.Column("intention_id", sa.UUID(), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
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
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            name="fk_intention_attachments_intention",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_intention_attachments_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_intention_attachments_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intention_attachments")),
    )
    op.create_index(
        op.f("ix_intention_attachments_workspace_id"), "intention_attachments", ["workspace_id"]
    )
    op.create_index(
        "ix_intention_attachments_intention",
        "intention_attachments",
        ["workspace_id", "intention_id"],
    )


def downgrade() -> None:
    op.drop_table("intention_attachments")
