"""The intelligence engine: its runs, their steps, the findings.

Revision ID: 2b8d4f6a1c93
Revises: 7e3a9c1b5f62
Created: 2026-10-05

LEKA-377. A run is one time LEKA analysed a workspace (`intelligence_runs`):
why, by whom, from which build of the model, which analyses, the
background job that ran it, what came of it. Each analysis of a run is a
step (`intelligence_steps`), pinned to its run's workspace: its version,
its time, what it found — or the error's type, why it was skipped. A
finding (`intelligence_findings`) is what an analysis concluded about one
thing, one row per analysis and key across runs: what it says, how bad,
how sure, what it is about, what shows it, where that was read, which runs
saw it, open or resolved.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2b8d4f6a1c93"
down_revision: str | None = "7e3a9c1b5f62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table(name: str, *columns: sa.Column[object], others: Sequence[object] = ()) -> None:
    """A workspace's table, as leka.db's mixin makes them."""
    op.create_table(
        name,
        *columns,
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
        *others,
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{name}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    op.create_index(op.f(f"ix_{name}_workspace_id"), name, ["workspace_id"])


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def upgrade() -> None:
    _table(
        "intelligence_runs",
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        _jsonb("requested", "[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("catalogue", sa.String(length=64), nullable=False),
        sa.Column("job_run_id", sa.UUID(), nullable=True),
        _jsonb("counts", "{}"),
        sa.Column("error", sa.String(length=200), nullable=True),
        others=(
            sa.CheckConstraint(
                "status IN ('running', 'succeeded', 'partial', 'failed', 'abandoned')",
                name=op.f("ck_intelligence_runs_status"),
            ),
            sa.CheckConstraint(
                "trigger IN ('model', 'schedule', 'request')",
                name=op.f("ck_intelligence_runs_trigger"),
            ),
            sa.CheckConstraint(
                "finished_at IS NULL OR finished_at >= started_at",
                name=op.f("ck_intelligence_runs_finished_after_started"),
            ),
            sa.ForeignKeyConstraint(
                ["requested_by"],
                ["users.id"],
                name=op.f("fk_intelligence_runs_requested_by_users"),
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint("workspace_id", "id", name="uq_intelligence_runs_workspace_id_id"),
        ),
    )
    op.create_index(
        "ix_intelligence_runs_workspace_started_at",
        "intelligence_runs",
        ["workspace_id", "started_at"],
    )

    _table(
        "intelligence_steps",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("analyzer", sa.String(length=60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        _jsonb("counts", "{}"),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.String(length=100), nullable=True),
        others=(
            sa.CheckConstraint(
                "status IN ('succeeded', 'failed', 'timed_out', 'skipped')",
                name=op.f("ck_intelligence_steps_status"),
            ),
            sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_intelligence_steps_duration")),
            # Pinned to its run's workspace.
            sa.ForeignKeyConstraint(
                ["workspace_id", "run_id"],
                ["intelligence_runs.workspace_id", "intelligence_runs.id"],
                name="fk_intelligence_steps_workspace_run",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("run_id", "analyzer", name="uq_intelligence_steps_run_analyzer"),
        ),
    )
    op.create_index(
        "ix_intelligence_steps_workspace_run", "intelligence_steps", ["workspace_id", "run_id"]
    )

    _table(
        "intelligence_findings",
        sa.Column("analyzer", sa.String(length=60), nullable=False),
        sa.Column("analyzer_version", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        _jsonb("params", "{}"),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("subject_name", sa.String(length=500), nullable=False),
        sa.Column("subject_kind", sa.String(length=50), nullable=True),
        _jsonb("related", "[]"),
        _jsonb("evidence", "[]"),
        _jsonb("provenance", "{}"),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_run_id", sa.UUID(), nullable=False),
        sa.Column("last_run_id", sa.UUID(), nullable=False),
        sa.Column("resolved_run_id", sa.UUID(), nullable=True),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reopened", sa.Integer(), server_default="0", nullable=False),
        others=(
            sa.CheckConstraint(
                "severity IN ('high', 'medium', 'low')",
                name=op.f("ck_intelligence_findings_severity"),
            ),
            sa.CheckConstraint(
                "status IN ('open', 'resolved')", name=op.f("ck_intelligence_findings_status")
            ),
            sa.CheckConstraint(
                "confidence >= 0 AND confidence <= 1",
                name=op.f("ck_intelligence_findings_confidence_range"),
            ),
            sa.CheckConstraint(
                "(status = 'resolved') = (resolved_at IS NOT NULL)",
                name=op.f("ck_intelligence_findings_resolved_when"),
            ),
            sa.UniqueConstraint(
                "workspace_id", "analyzer", "key", name="uq_intelligence_findings_analyzer_key"
            ),
        ),
    )
    op.create_index(
        "ix_intelligence_findings_workspace_rank",
        "intelligence_findings",
        ["workspace_id", "status", "rank"],
    )
    op.create_index(
        "ix_intelligence_findings_workspace_seen",
        "intelligence_findings",
        ["workspace_id", "last_seen_at"],
    )
    op.create_index(
        "ix_intelligence_findings_workspace_subject",
        "intelligence_findings",
        ["workspace_id", "subject_id"],
    )


def downgrade() -> None:
    op.drop_table("intelligence_findings")
    op.drop_table("intelligence_steps")
    op.drop_table("intelligence_runs")
