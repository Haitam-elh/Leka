"""job_runs: what was done about an event, and how it went.

Revision ID: c327b838b263
Revises: 87a4e899df19
Created: 2026-09-22

LEKA-334. One table; docs/adr/013-events-and-job-runs.md says why.

**job_runs has NO workspace_id.** A sweep serves every customer and belongs to
none, so its owner is NULL, and a nullable workspace_id is what
test_workspace_id_is_never_nullable exists to forbid — it would look like the
isolation column while nothing protected it. The column is called
for_workspace_id and the table is listed as tenant-free.

Three guarantees live in the schema, because a check in application code has a
race between the check and the write and a constraint does not:

  - the same event cannot create the same job's run twice
    (uq_job_runs_event_id_job)
  - two runs cannot both be ACTIVE for one concurrency key
    (uq_job_runs_active_key_*, two indexes because NULLs are distinct)
  - a run cannot point at another workspace's event (the composite foreign key,
    plus a CHECK, since MATCH SIMPLE skips the key when the workspace is NULL)

`ON DELETE SET NULL (event_id)` clears ONLY the event reference. A plain SET
NULL would also null for_workspace_id and quietly turn a customer's run into a
system run when its event was pruned. The column list needs PostgreSQL 15; the
project runs 16. `for_workspace_id` cascades: erasing a customer erases their
history.

**enqueued_at is what makes the table a second outbox.** A run is created in the
database; a separate pass puts it on the Redis queue and stamps this column. A
run with `status = 'queued' AND enqueued_at IS NULL` has not reached the queue
yet, whatever the reason, and the next pass takes it. Status and enqueued_at are
different questions — "where is this job in its life" and "does Redis know" — and
a run the queue forgot is found by the second, not guessed from the first.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c327b838b263"
down_revision: str | None = "87a4e899df19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE = "'queued', 'running', 'retrying'"


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        # NOT called workspace_id, and nullable: see the module docstring.
        sa.Column("for_workspace_id", sa.UUID(), nullable=True),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.Column("job", sa.String(length=300), nullable=False),
        sa.Column(
            "args",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "kwargs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("queue", sa.String(length=50), server_default="leka", nullable=False),
        sa.Column("status", sa.String(length=50), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("concurrency_key", sa.String(length=200), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # clock_timestamp(), not now(): now() is the START OF THE TRANSACTION, so
        # every run created by one dispatcher pass would share a created_at and
        # their order — which is the order the events arrived in — would be lost.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'retrying', 'succeeded', 'failed')",
            name=op.f("ck_job_runs_status"),
        ),
        sa.CheckConstraint(
            "queue IN ('leka:high', 'leka', 'leka:low')", name=op.f("ck_job_runs_queue")
        ),
        # 0 reads as "disabled" to whoever types it and "never try" to the code.
        sa.CheckConstraint("max_attempts >= 1", name=op.f("ck_job_runs_max_attempts_positive")),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= max_attempts",
            name=op.f("ck_job_runs_attempts_in_range"),
        ),
        # MATCH SIMPLE skips the composite key when for_workspace_id is NULL, so
        # an event reference without a workspace would be unconstrained.
        sa.CheckConstraint(
            "event_id IS NULL OR for_workspace_id IS NOT NULL",
            name=op.f("ck_job_runs_event_requires_workspace"),
        ),
        sa.ForeignKeyConstraint(
            ["for_workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_job_runs_for_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["for_workspace_id", "event_id"],
            ["events.workspace_id", "events.id"],
            name="fk_job_runs_workspace_event",
            # Only event_id is cleared: a plain SET NULL would null
            # for_workspace_id too and turn a customer's run into a system run.
            ondelete="SET NULL (event_id)",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
        # One event yields one run per job: a dispatcher that dies after creating
        # the runs and tries again gets a refusal, not a second execution.
        sa.UniqueConstraint("event_id", "job", name="uq_job_runs_event_id_job"),
    )
    # At most one ACTIVE run per concurrency key, per owner. Two indexes,
    # because NULLs are distinct in a unique index and a system sweep has no
    # workspace: with one, two workers could run the same sweep at once.
    op.create_index(
        "uq_job_runs_active_key_workspace",
        "job_runs",
        ["for_workspace_id", "concurrency_key"],
        unique=True,
        postgresql_where=sa.text(f"for_workspace_id IS NOT NULL AND status IN ({_ACTIVE})"),
    )
    op.create_index(
        "uq_job_runs_active_key_system",
        "job_runs",
        ["concurrency_key"],
        unique=True,
        postgresql_where=sa.text(f"for_workspace_id IS NULL AND status IN ({_ACTIVE})"),
    )
    # A customer's history, most recent first. Also covers the cascade from
    # workspaces, which would otherwise scan the table per deleted workspace.
    op.create_index(
        "ix_job_runs_for_workspace_id_created_at",
        "job_runs",
        ["for_workspace_id", "created_at"],
    )
    # The retry pass: which retries are due.
    op.create_index(
        "ix_job_runs_retrying_next_run_at",
        "job_runs",
        ["next_run_at"],
        postgresql_where=sa.text("status = 'retrying'"),
    )
    # Recovery: which running jobs have lost their worker.
    op.create_index(
        "ix_job_runs_running_locked_until",
        "job_runs",
        ["locked_until"],
        postgresql_where=sa.text("status = 'running'"),
    )
    # The enqueue pass: runs the queue has not been told about yet, oldest first.
    op.create_index(
        "ix_job_runs_unenqueued",
        "job_runs",
        ["created_at"],
        postgresql_where=sa.text("status = 'queued' AND enqueued_at IS NULL"),
    )
    # The stale pass: queued runs the queue was told about long ago.
    op.create_index(
        "ix_job_runs_queued_enqueued_at",
        "job_runs",
        ["enqueued_at"],
        postgresql_where=sa.text("status = 'queued' AND enqueued_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the table.

    Nothing outside the database is touched. A job already on the RQ queue keeps
    existing there with no row to describe it, and will find nothing to claim
    and do nothing; drain the queue first if that matters.
    """
    op.drop_index("ix_job_runs_queued_enqueued_at", table_name="job_runs")
    op.drop_index("ix_job_runs_unenqueued", table_name="job_runs")
    op.drop_index("ix_job_runs_running_locked_until", table_name="job_runs")
    op.drop_index("ix_job_runs_retrying_next_run_at", table_name="job_runs")
    op.drop_index("ix_job_runs_for_workspace_id_created_at", table_name="job_runs")
    op.drop_index("uq_job_runs_active_key_system", table_name="job_runs")
    op.drop_index("uq_job_runs_active_key_workspace", table_name="job_runs")
    op.drop_table("job_runs")
