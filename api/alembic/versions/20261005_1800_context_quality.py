"""Context quality: how good a version is, and what people say of it.

Revision ID: 7e3a9c1b5f62
Revises: 5c7e1f9a2d34
Created: 2026-10-05

LEKA-375. A version keeps how good it was judged when it was made
(`context_versions.quality`): its completeness, freshness and confidence,
each with what it was read from, what it lacks, what it disagrees on and
how badly, what each retriever brought. The versions made before hold
none; they are judged when read. What people say of a version — an
element useful, not useful, wrong, or something missing — is kept
(`context_feedback`), with what the element was then.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7e3a9c1b5f62"
down_revision: str | None = "5c7e1f9a2d34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "context_versions",
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "context_feedback",
        sa.Column("context_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ref_id", sa.UUID(), nullable=True),
        sa.Column("label", sa.String(length=500), nullable=True),
        sa.Column("ref_type", sa.String(length=50), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column(
            "retrievers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("given_by", sa.UUID(), nullable=True),
        sa.Column("given_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "verdict IN ('useful', 'not_useful', 'wrong', 'missing')",
            name=op.f("ck_context_feedback_verdict"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_context_feedback_version")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "context_id"],
            ["contexts.workspace_id", "contexts.id"],
            name="fk_context_feedback_workspace_context",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["given_by"],
            ["users.id"],
            name=op.f("fk_context_feedback_given_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_context_feedback_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_context_feedback")),
    )
    op.create_index(op.f("ix_context_feedback_workspace_id"), "context_feedback", ["workspace_id"])
    op.create_index(
        "ix_context_feedback_workspace_context",
        "context_feedback",
        ["workspace_id", "context_id", "given_at"],
    )
    op.create_index(
        "ix_context_feedback_workspace_given_at", "context_feedback", ["workspace_id", "given_at"]
    )


def downgrade() -> None:
    op.drop_table("context_feedback")
    op.drop_column("context_versions", "quality")
