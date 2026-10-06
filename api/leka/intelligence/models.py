"""Tables owned by the intelligence module (LEKA-377).

A RUN is one time LEKA analysed a workspace's knowledge: why — the company
model changed, the hourly sweep, someone asked — by whom, from which build
of the model, which analyses, and what came of it. Each analysis of a run is
a STEP: its version, how long it took, what it found — or why it failed,
timed out or was skipped. A step that fails is that analysis's failure,
never the run's or the others': the rest go on.

A FINDING is what an analysis concluded about one thing — a service no team
owns, a database eight things rely on and nothing watches, a context behind
the model — kept across runs under one key: seen again, it is updated; no
longer seen, it is resolved; seen once more, reopened. Each says what it is
about, how bad, how sure, what shows it (`evidence`) and where that was read
(`provenance`), and which runs first saw it, last saw it, resolved it.

No foreign key from a finding to its runs, nor to the entity or context it
is about: runs are pruned and things go, and a finding must still say what
it was. docs/intelligence.md says why each column is here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin

RUN_STATUSES = ("running", "succeeded", "partial", "failed", "abandoned")
RUN_TRIGGERS = ("model", "schedule", "request")
STEP_STATUSES = ("succeeded", "failed", "timed_out", "skipped")
SEVERITIES = ("high", "medium", "low")
FINDING_STATUSES = ("open", "resolved")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class IntelligenceRun(Base, WorkspaceScopedMixin):
    """One time LEKA analysed a workspace: why, from what, what came of it."""

    __tablename__ = "intelligence_runs"
    __table_args__ = (
        # The target for intelligence_steps' own: a step can never belong to
        # another tenant's run.
        UniqueConstraint("workspace_id", "id", name="uq_intelligence_runs_workspace_id_id"),
        CheckConstraint(_in("status", RUN_STATUSES), name="status"),
        CheckConstraint(_in("trigger", RUN_TRIGGERS), name="trigger"),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"
        ),
        Index("ix_intelligence_runs_workspace_started_at", "workspace_id", "started_at"),
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")
    # model: the company model was built again; schedule: the hourly sweep;
    # request: someone asked.
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # The analyses asked for by name; empty: every one.
    requested: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # From which build of the company model: the basis every finding of the
    # run was read from.
    model_built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The analyses' versions, hashed: a new version is something to run again.
    catalogue: Mapped[str] = mapped_column(String(64), nullable=False)
    # The background job that ran it (job_runs, ADR 013): its id, its logs'
    # run_id. No foreign key: that history is pruned.
    job_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # What it did, counted: findings opened, seen again, resolved, reopened;
    # analyses that succeeded, failed, were skipped.
    counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Why the run itself stopped, when it did: the error's type, never its
    # text — that is the logs'.
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)


class IntelligenceStep(Base, WorkspaceScopedMixin):
    """One analysis of a run: its version, its time, what it found — or why
    it did not."""

    __tablename__ = "intelligence_steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["intelligence_runs.workspace_id", "intelligence_runs.id"],
            name="fk_intelligence_steps_workspace_run",
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "analyzer", name="uq_intelligence_steps_run_analyzer"),
        CheckConstraint(_in("status", STEP_STATUSES), name="status"),
        CheckConstraint("duration_ms >= 0", name="duration"),
        Index("ix_intelligence_steps_workspace_run", "workspace_id", "run_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    analyzer: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Found, opened, seen again, resolved, reopened.
    counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Failed or timed out: the error's type. Skipped: why, in a word —
    # no_model, no_material.
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Finding(Base, WorkspaceScopedMixin):
    """What an analysis concluded about one thing, kept across runs."""

    __tablename__ = "intelligence_findings"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "analyzer", "key", name="uq_intelligence_findings_analyzer_key"
        ),
        CheckConstraint(_in("severity", SEVERITIES), name="severity"),
        CheckConstraint(_in("status", FINDING_STATUSES), name="status"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("(status = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_when"),
        Index("ix_intelligence_findings_workspace_rank", "workspace_id", "status", "rank"),
        Index("ix_intelligence_findings_workspace_seen", "workspace_id", "last_seen_at"),
        Index("ix_intelligence_findings_workspace_subject", "workspace_id", "subject_id"),
    )

    analyzer: Mapped[str] = mapped_column(String(60), nullable=False)
    analyzer_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Its identity within its analysis: the thing, and what of it — the same
    # key run after run is the same finding.
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    # What it says, as a code and its values — the interface words them —
    # and as one English sentence, for what reads it without a dictionary.
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    # Its place among the others: severity first, then how much it weighs.
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # What it is about: an entity, a context — its id, its name then.
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(500), nullable=False)
    subject_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # The other things it involves, and what shows it.
    related: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    evidence: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # Where that was read: the build of the model, the sources, the context
    # version, the analysis and its version.
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resolved_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # How many runs saw it, and how many times it came back once resolved.
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    reopened: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
