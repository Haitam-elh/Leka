"""LLM runtime: every piece of work a language model did, and its calls.

Revision ID: 5e2a7c9b1d38
Revises: 2e7b4c9a1f58
Created: 2026-10-10

LEKA-429. Each task a LEKA feature had a model do (`llm_runs`): for what,
about what, how it ended — succeeded, invalid, no_model, timed_out, failed —
who answered (provider, model, version), its calls, tokens, cost and
latency, the LEKA context it was given. Each call to a model now says which
of them it was part of (`model_calls.run_id`).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5e2a7c9b1d38"
down_revision: str | None = "2e7b4c9a1f58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_runs",
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("ref", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("version", sa.String(length=120), nullable=True),
        sa.Column("calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("context_ref", sa.String(length=200), nullable=True),
        sa.Column("context_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
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
            name=op.f("fk_llm_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_runs")),
    )
    op.create_index(op.f("ix_llm_runs_workspace_id"), "llm_runs", ["workspace_id"], unique=False)
    op.create_index(
        "ix_llm_runs_workspace_started", "llm_runs", ["workspace_id", "started_at"], unique=False
    )
    op.add_column("model_calls", sa.Column("run_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_model_calls_run_id"), "model_calls", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_model_calls_run_id"), table_name="model_calls")
    op.drop_column("model_calls", "run_id")
    op.drop_index("ix_llm_runs_workspace_started", table_name="llm_runs")
    op.drop_index(op.f("ix_llm_runs_workspace_id"), table_name="llm_runs")
    op.drop_table("llm_runs")
