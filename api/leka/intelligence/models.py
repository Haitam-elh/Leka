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

A CANDIDATE (LEKA-380) is an enrichment of the company model an analysis
proposed — a relationship, an attribute — waiting for a decision, applied
once validated.

A CONFLICT (LEKA-382) is what the model's sources disagree on, with LEKA's
recommendation and every decision taken on it; an AUTHORITY RULE, how much
the workspace says a source is to be believed.

No foreign key from a finding to its runs, nor to the entity or context it
is about: runs are pruned and things go, and a finding must still say what
it was. docs/intelligence.md says why each column is here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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
    # What refers to an entity: hidden with it (LEKA-402).
    __entity_refs__ = ("subject_id",)
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


CANDIDATE_STATUSES = ("proposed", "accepted", "rejected", "withdrawn")
CANDIDATE_KINDS = ("relationship", "attribute")
DECIDED_VIA = ("person", "policy")


class EnrichmentCandidate(Base, WorkspaceScopedMixin):
    """An enrichment of the company model an analysis proposed (LEKA-380),
    kept until someone decides — one row per key across runs.

        proposed   waiting: seen again, it is updated; no longer seen, it
                   is withdrawn — its evidence went
        accepted   validated by a person, or by the policy (what is sure
                   and adds without replacing): applied to the model by
                   leka.knowledge's next build, as a fact of its own
                   (model_assertions, under this row's id)
        rejected   a person said no: never proposed again under its key,
                   and — if it had been accepted — withdrawn from the model
        withdrawn  no longer proposed; seen again, proposed again

    What it proposes: a relationship (`relationship`, from `start` to
    `end`) or an attribute (`attribute`, `value`; `current`, what the
    model said then). `overrides`: accepting it replaces what a source
    says — only a person may, and says so. Each keeps how sure, what shows
    it (`evidence`) and where that was read (`provenance`), like a finding.
    """

    __tablename__ = "enrichment_candidates"
    # What refers to an entity: hidden with it (LEKA-402).
    __entity_refs__ = ("subject_id",)
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_enrichment_candidates_key"),
        CheckConstraint(_in("status", CANDIDATE_STATUSES), name="status"),
        CheckConstraint(_in("kind", CANDIDATE_KINDS), name="kind"),
        CheckConstraint(
            f"decided_via IS NULL OR {_in('decided_via', DECIDED_VIA)}", name="decided_via"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "(status IN ('accepted', 'rejected')) = (decided_at IS NOT NULL)", name="decided_when"
        ),
        Index("ix_enrichment_candidates_workspace_status", "workspace_id", "status"),
        Index("ix_enrichment_candidates_workspace_seen", "workspace_id", "last_seen_at"),
        Index("ix_enrichment_candidates_workspace_subject", "workspace_id", "subject_id"),
    )

    analyzer: Mapped[str] = mapped_column(String(60), nullable=False)
    analyzer_version: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    # relationship, semantic, organisation, business
    family: Mapped[str] = mapped_column(String(30), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # The thing it enriches.
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(500), nullable=False)
    subject_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # A relationship: its kind, its ends — their names then.
    relationship: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    start_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    end_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    end_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    end_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # An attribute: which, the value proposed, what the model said then.
    attribute: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    current: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    overrides: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # The build of the model it read, its sources' kinds, the analysis.
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="proposed")
    decided_via: Mapped[str | None] = mapped_column(String(10), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Every decision taken on it, the latest last: {status, via, by, at,
    # reason} — accepted, then rejected, then reprocessed is three.
    history: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


CONFLICT_STATUSES = ("open", "resolved", "dismissed", "gone")
CONFLICT_KINDS = ("attribute", "relationship")
STANCES = ("prefer", "avoid")


class KnowledgeConflict(Base, WorkspaceScopedMixin):
    """What the model's sources disagree on (LEKA-382), one row per thing and
    what about across runs — an attribute two sources say differently, a
    relationship a thing has one of said to several — with every side, who
    says it, how much each source is to be believed, and what LEKA
    recommends.

        open       waiting for someone: seen again, updated; no longer seen —
                   the sources agree now, or the thing went — gone
        resolved   someone kept one side: the model shows it from the next
                   build on, whoever says otherwise (facts in
                   model_assertions, provenance.conflict_id = this row)
        dismissed  someone said it is no contradiction
        gone       no longer disagreed on

    A resolved or dismissed conflict reopens when a value appears that no
    one decided on (`decided_values`). Nothing is overwritten silently: the
    decision is a person's, every one kept in `history`.
    """

    __tablename__ = "knowledge_conflicts"
    # What refers to an entity: hidden with it (LEKA-402).
    __entity_refs__ = ("subject_id",)
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_knowledge_conflicts_key"),
        CheckConstraint(_in("status", CONFLICT_STATUSES), name="status"),
        CheckConstraint(_in("kind", CONFLICT_KINDS), name="kind"),
        Index("ix_knowledge_conflicts_workspace_status", "workspace_id", "status"),
        Index("ix_knowledge_conflicts_workspace_seen", "workspace_id", "last_seen_at"),
        Index("ix_knowledge_conflicts_workspace_subject", "workspace_id", "subject_id"),
    )

    key: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(500), nullable=False)
    subject_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # The attribute — or, for a relationship, its role: owner, manager.
    about: Mapped[str] = mapped_column(String(100), nullable=False)
    relationship: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # What the model shows now.
    chosen: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    # Every side: {value, ref_id, origin, sources: [{source_id, kind, name,
    # status, observed_at, authority, rule}], authority, freshness,
    # corroboration, score, edges}.
    sides: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # What LEKA recommends: {side, strength (rule, clear, weak, none),
    # reasons, margin}.
    recommendation: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    # The decision standing: {side, value, via, by, at, reason}; the values
    # known when it was taken.
    resolution: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    decided_values: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    history: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class AuthorityRule(Base, WorkspaceScopedMixin):
    """How much a source is to be believed, said by the workspace (LEKA-382):
    on an attribute — or a role, or everything (`*`) — this source is to be
    preferred, or avoided. LEKA's recommendations follow it; it decides
    nothing by itself."""

    __tablename__ = "authority_rules"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "about", "source_id", name="uq_authority_rules_about_source"
        ),
        CheckConstraint(_in("stance", STANCES), name="stance"),
    )

    about: Mapped[str] = mapped_column(String(100), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    stance: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


QUALITY_SCOPES = ("entity", "team", "application", "column", "workspace")
QUALITY_LEVELS = ("high", "medium", "low")
_DIMENSIONS = ("completeness", "freshness", "consistency", "confidence")


def _unit(column: str) -> str:
    return f"{column} IS NULL OR ({column} >= 0 AND {column} <= 1)"


class QualityScoreRow(Base, WorkspaceScopedMixin):
    """How far what LEKA knows of one thing or one area can be trusted now
    (LEKA-381) — one row per key, rewritten by each run that measures it,
    gone when it is no longer measured: its score, level and dimensions,
    the factors read (`factors`), what lowers it (`missing`), the areas it
    counts in, where it was read."""

    __tablename__ = "quality_scores"
    # What refers to an entity: hidden with it (LEKA-402).
    __entity_refs__ = ("subject_id",)
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_quality_scores_key"),
        CheckConstraint(_in("scope", QUALITY_SCOPES), name="scope"),
        CheckConstraint(_in("level", QUALITY_LEVELS), name="level"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        *(CheckConstraint(_unit(name), name=f"{name}_range") for name in _DIMENSIONS),
        Index("ix_quality_scores_workspace_scope_score", "workspace_id", "scope", "score"),
        Index("ix_quality_scores_workspace_subject", "workspace_id", "subject_id"),
    )

    key: Mapped[str] = mapped_column(String(300), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(500), nullable=False)
    subject_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # An entity's column of Mon environnement.
    column: Mapped[str | None] = mapped_column(String(20), nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    # Each dimension; none when nothing measures it.
    completeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    freshness: Mapped[float | None] = mapped_column(Float, nullable=True)
    consistency: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # An entity's: each dimension's factors. An area's: its levels counted,
    # its weakest things.
    factors: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # What lowers it, the heaviest first: {code, dimension, weight, detail}
    # — an area's: {code, count}.
    missing: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    areas: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    entities: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    capped: Mapped[str | None] = mapped_column(String(30), nullable=True)
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Since when it holds its level.
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QualityPoint(Base, WorkspaceScopedMixin):
    """One point of a score's history (LEKA-381): written when it is first
    measured, and each time it moves — by 0.02 or more, or to another level
    — so a series is its changes, not a row per run. Kept a year."""

    __tablename__ = "quality_history"
    # What refers to an entity: hidden with it (LEKA-402).
    __entity_refs__ = ("subject_id",)
    __table_args__ = (
        CheckConstraint(_in("scope", QUALITY_SCOPES), name="scope"),
        CheckConstraint(_in("level", QUALITY_LEVELS), name="level"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        Index("ix_quality_history_workspace_key_at", "workspace_id", "key", "measured_at"),
        Index("ix_quality_history_workspace_at", "workspace_id", "measured_at"),
    )

    key: Mapped[str] = mapped_column(String(300), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    completeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    freshness: Mapped[float | None] = mapped_column(Float, nullable=True)
    consistency: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
