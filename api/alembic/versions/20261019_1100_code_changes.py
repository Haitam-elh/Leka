"""Code changes: what the code-change agent proposes, and what came of it.

Revision ID: 4e7a2c9d1b63
Revises: 0a074280012e
Created: 2026-10-19

One row per change an agent proposed (`code_changes`): the run and the
intention it answers, the GitHub source and repository, the branch its files
were read from, each file as it would be with its diff — and where it
stands: proposed, rejected, or applied as a pull request (its branch, number,
address), or why its pull request could not be opened.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4e7a2c9d1b63"
down_revision: str | None = "0a074280012e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "code_changes",
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("intention_id", sa.UUID(), nullable=True),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("repository", sa.String(length=200), nullable=False),
        sa.Column("base_branch", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("proposed_by", sa.UUID(), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("branch", sa.String(length=250), nullable=True),
        sa.Column("pull_request_number", sa.Integer(), nullable=True),
        sa.Column("pull_request_url", sa.String(length=500), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("error", sa.String(length=40), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
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
            "status IN ('proposed', 'rejected', 'applied', 'failed')",
            name=op.f("ck_code_changes_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_code_changes_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by"],
            ["users.id"],
            name=op.f("fk_code_changes_proposed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_code_changes_decided_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_code_changes_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_changes")),
    )
    op.create_index(
        op.f("ix_code_changes_workspace_id"), "code_changes", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_code_changes_workspace_intention", "code_changes", ["workspace_id", "intention_id"]
    )
    op.create_index("ix_code_changes_workspace_run", "code_changes", ["workspace_id", "run_id"])


def downgrade() -> None:
    op.drop_index("ix_code_changes_workspace_run", table_name="code_changes")
    op.drop_index("ix_code_changes_workspace_intention", table_name="code_changes")
    op.drop_index(op.f("ix_code_changes_workspace_id"), table_name="code_changes")
    op.drop_table("code_changes")
