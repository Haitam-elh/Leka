"""What the intelligence API says (LEKA-377): the analyses there are, the
runs and what each analysis of them did, the findings and what shows them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SeverityName = Literal["high", "medium", "low"]
FindingStatus = Literal["open", "resolved"]


class AnalyzerRead(BaseModel):
    """One analysis LEKA runs: what it reads, how it reasons, whether it can
    run here and now."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    category: str = Field(description="architecture, organisation, context…")
    method: Literal["rules", "model"]
    reads: list[Literal["model", "context"]]
    summary: str = Field(description="What it looks for (English).")
    available: bool = Field(description="False for a model-assisted one: no model gateway yet.")


class AnalysisRequest(BaseModel):
    """Analyse now. Every analysis, or those named."""

    model_config = ConfigDict(extra="forbid")

    analyzers: list[str] | None = Field(
        default=None, max_length=50, description="Their names; none: every one."
    )


class AnalysisRequested(BaseModel):
    """`queued` is false when a run is already on its way: it will be the
    one that answers."""

    model_config = ConfigDict(frozen=True)

    queued: bool


class StepRead(BaseModel):
    """One analysis of a run: what it did, or why it did not."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    analyzer: str
    version: int
    status: Literal["succeeded", "failed", "timed_out", "skipped"]
    started_at: datetime
    duration_ms: int
    counts: dict[str, int] = Field(description="found, opened, seen (again), resolved, reopened.")
    error: str | None = Field(description="Failed or timed out: the error's type.")
    reason: str | None = Field(description="Skipped: no_model, no_material.")


class RunRead(BaseModel):
    """One time LEKA analysed the workspace."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    status: Literal["running", "succeeded", "partial", "failed", "abandoned"]
    trigger: Literal["model", "schedule", "request"]
    requested_by: uuid.UUID | None
    requested: list[str] = Field(description="The analyses asked for; empty: every one.")
    started_at: datetime
    finished_at: datetime | None
    model_built_at: datetime | None = Field(description="The build of the model it read.")
    job_run_id: uuid.UUID | None = Field(description="The background job that ran it.")
    counts: dict[str, int]
    error: str | None


class RunDetail(RunRead):
    steps: list[StepRead]


class SubjectRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["entity", "context"]
    id: uuid.UUID | None
    name: str
    kind: str | None


class EvidenceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str = Field(description="entity, relationship, context.")
    id: str | None
    name: str
    detail: str = Field(description="What it shows (English).")


class FindingRead(BaseModel):
    """What an analysis concluded about one thing."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    analyzer: str
    analyzer_version: int
    category: str
    code: str = Field(description="What it says, for the interface to word.")
    params: dict[str, object] = Field(description="The values the code is worded with.")
    statement: str = Field(description="What it says, in English.")
    severity: SeverityName
    rank: int = Field(description="Its place: severity first (300s high), then its weight.")
    confidence: float
    subject: SubjectRead
    status: FindingStatus
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    occurrences: int = Field(description="How many runs saw it.")


class FindingDetail(FindingRead):
    """And what shows it, where that was read, which runs saw it."""

    related: list[SubjectRead]
    evidence: list[EvidenceRead]
    provenance: dict[str, object] = Field(
        description="The build of the model, the sources' kinds, the context version, "
        "the analysis and its version."
    )
    first_run_id: uuid.UUID
    last_run_id: uuid.UUID
    resolved_run_id: uuid.UUID | None
    reopened: int


class IntelligenceSummary(BaseModel):
    """Where the workspace's analysis stands: what is open, how bad, the
    most pressing — for a product surface to show at a glance."""

    model_config = ConfigDict(frozen=True)

    open: dict[str, int] = Field(description="The open findings, by severity.")
    top: list[FindingRead] = Field(description="The most pressing open ones.")
    latest: RunRead | None = Field(description="The latest run, whatever came of it.")
