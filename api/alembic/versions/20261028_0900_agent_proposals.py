"""What LEKA proposes to send out of a run's deliverable: tickets for a Jira
project, pages for a Confluence space — drafted, chosen and accepted by a
person, then created through the source when its admin allowed it.

Revision ID: c184793fb3fb
Revises: adee2d9b1cf5
Created: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c184793fb3fb"
down_revision: str | None = "adee2d9b1cf5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_proposals",
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("intention_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=300), server_default="", nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "items", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("proposed_by", sa.UUID(), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "results", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
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
        sa.CheckConstraint("kind IN ('issues', 'pages')", name=op.f("ck_agent_proposals_kind")),
        sa.CheckConstraint(
            "status IN ('drafting', 'proposed', 'applied', 'partly', 'rejected', 'failed')",
            name=op.f("ck_agent_proposals_status"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_agent_proposals_decided_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by"],
            ["users.id"],
            name=op.f("fk_agent_proposals_proposed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_agent_proposals_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_proposals_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_proposals")),
    )
    op.create_index(
        op.f("ix_agent_proposals_workspace_id"), "agent_proposals", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_agent_proposals_workspace_intention",
        "agent_proposals",
        ["workspace_id", "intention_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_proposals_workspace_run",
        "agent_proposals",
        ["workspace_id", "run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_proposals_workspace_run", table_name="agent_proposals")
    op.drop_index("ix_agent_proposals_workspace_intention", table_name="agent_proposals")
    op.drop_index(op.f("ix_agent_proposals_workspace_id"), table_name="agent_proposals")
    op.drop_table("agent_proposals")
