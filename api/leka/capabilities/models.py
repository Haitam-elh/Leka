"""Tables owned by the capabilities module.

The catalogue's history (LEKA-393), LEKA's and no customer's: every version
of every capability ever registered — what it was (its fingerprint), where
it stood in its lifecycle — and every event of that history, append-only.
And each workspace's say on them: enabled or not, and its people's
favourites. And every run of an agent, with its steps (LEKA-395); every run
of a skill (LEKA-396).

Agents themselves are never stored here. They are files in agents/
(architecture rule 8); what is kept is that they were registered, as what.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class CapabilityRegistration(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One version of one capability, as it was registered. LEKA's
    catalogue, not a tenant's: no workspace_id (test_tenant_isolation)."""

    __tablename__ = "capability_registrations"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_capability_registrations_key_version"),
        Index("ix_capability_registrations_key", "key"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(12), nullable=False)
    # What it is and does, hashed (definition.fingerprint).
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # What the catalogue says of it — an agent's instructions only hashed.
    definition: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lifecycle_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When a later version took its place.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CapabilityEvent(Base, UUIDPrimaryKeyMixin):
    """One thing that happened in the catalogue: registered, moved in its
    lifecycle, superseded, refused — when, why. Append-only: the database
    refuses to change one."""

    __tablename__ = "capability_events"
    __table_args__ = (Index("ix_capability_events_key_at", "key", "at"),)

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    # registered, lifecycle_changed, superseded, refused
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    from_lifecycle: Mapped[str | None] = mapped_column(String(12), nullable=True)
    to_lifecycle: Mapped[str | None] = mapped_column(String(12), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class WorkspaceCapability(Base, WorkspaceScopedMixin):
    """A workspace's say on one capability: enabled, or not and why. None:
    enabled."""

    __tablename__ = "workspace_capabilities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_workspace_capabilities_key"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CapabilityFavourite(Base, WorkspaceScopedMixin):
    """A capability a person keeps at hand: « Mes capacités »."""

    __tablename__ = "capability_favourites"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "key", name="uq_capability_favourites_key"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)


class CapabilitySuggestion(Base, WorkspaceScopedMixin):
    """An agent or a skill someone wishes LEKA had (LEKA-501): sent to LEKA's
    team, never an intention — nothing runs on it. Its status is the team's
    to move (python -m leka.capabilities.suggestions)."""

    __tablename__ = "capability_suggestions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received', 'reviewing', 'planned', 'declined', 'done')",
            name="status",
        ),
        Index("ix_capability_suggestions_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    use_case: Mapped[str] = mapped_column(Text, nullable=False)
    systems: Mapped[str | None] = mapped_column(String(300), nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="received")


class WorkspaceModel(Base, WorkspaceScopedMixin):
    """A workspace's own language model (LEKA-394) — its Google, Mistral,
    OpenAI, Anthropic account, or its company's Azure OpenAI — used before
    LEKA's: its key encrypted (secret_box), never shown again; whether it
    answered when last tested. `exclusive`: this model only, never LEKA's —
    the company's data goes to its own contract or nowhere."""

    __tablename__ = "workspace_models"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_workspace_models_workspace"),)

    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    # The model, or the Azure deployment; none: the provider's default.
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    key_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_hint: Mapped[str | None] = mapped_column(String(8), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # untested, ok, failed
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="untested")
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelRate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """What a model costs LEKA from a day on (LEKA-430), per million tokens,
    in US dollars — LEKA's and no customer's. A new price is a new row from
    its day: a rate is never rewritten (the database refuses it), so a call
    priced with it (model_calls.rate_id) can be priced again, the same.
    Seeded with the list prices of profiles.py; a model with no rate has no
    cost — unknown, never 0."""

    __tablename__ = "model_rates"
    __table_args__ = (
        UniqueConstraint("provider", "model", "since", name="uq_model_rates_provider_model_since"),
        CheckConstraint(
            "per_million_in >= 0 AND per_million_out >= 0"
            " AND (per_million_cached IS NULL OR per_million_cached >= 0)",
            name="positive",
        ),
    )

    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    since: Mapped[date] = mapped_column(Date, nullable=False)
    per_million_in: Mapped[float] = mapped_column(Float, nullable=False)
    per_million_out: Mapped[float] = mapped_column(Float, nullable=False)
    # A token read from the provider's cache; none: as any token in.
    per_million_cached: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Where the price was read: a provider's page, a contract.
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ModelCall(Base, WorkspaceScopedMixin):
    """One call to a language model: for what, about what, to whom — the
    provider, the model, the version it said — what it cost, how long; or
    why it failed. What answers « why did LEKA say that? » and « what does
    it spend? »."""

    __tablename__ = "model_calls"
    __table_args__ = (
        Index("ix_model_calls_workspace_at", "workspace_id", "at"),
        # The usage ledger reads an execution's calls by what they are about.
        Index("ix_model_calls_workspace_ref", "workspace_id", "ref"),
        Index("ix_model_calls_rate_id", "rate_id"),
    )

    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The runtime's execution it was part of (LEKA-429).
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    tier: Mapped[str] = mapped_column(String(10), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # own, default, fallback, alternative — and which try of it.
    route: Mapped[str] = mapped_column(String(12), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # The workspace's own model, or LEKA's.
    owner: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # ok, failed, invalid
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_thinking: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Of tokens_in, those read from the provider's cache — billed less.
    tokens_cached: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Whether the provider said what the call used (LEKA-430): its tokens
    # measured, or not known — none for the calls kept before it was asked.
    usage_reported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The rate it was priced with (LEKA-430): its cost can be read again.
    rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_rates.id", ondelete="RESTRICT"), nullable=True
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The person it was asked for (LEKA-406) — none for LEKA's own work;
    # forgotten with their account.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AgentRun(Base, WorkspaceScopedMixin):
    """One run of an agent (LEKA-395): which agent, which version, asked by
    whom with what, on which context — where it stands, what it delivered,
    which model answered, or why it failed. Its steps are its events."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_approval', 'queued', 'running', 'succeeded', 'failed',"
            " 'cancelled')",
            name="status",
        ),
        Index("ix_agent_runs_workspace_queued", "workspace_id", "queued_at"),
        UniqueConstraint("workspace_id", "id", name="uq_agent_runs_workspace_id_id"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    # awaiting_approval (LEKA-406): twenty.
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # What it was given, as its contract takes it.
    inputs: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # What it was asked for, when it was: an intention (LEKA-384) — no
    # foreign key, capabilities sits below intentions.
    intention_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # The context it read: which, which version — kept when the context is
    # archived, as an analysis keeps it.
    context_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    context_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # markdown or json; what it declares and the runtime does not render
    # yet is in detail.pending.
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Why it failed (runtime.FAILURES), or who cancelled it.
    error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # The model whose answer it delivered.
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRunEvent(Base, WorkspaceScopedMixin):
    """One step of a run: queued, started, its context injected, a tool
    withheld or called — and what came of it — the model's answer, how it
    ended. Append-only: the database refuses to change one."""

    __tablename__ = "agent_run_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            ondelete="CASCADE",
            name="fk_agent_run_events_run",
        ),
        Index("ix_agent_run_events_run", "run_id", "at", "seq"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # queued, started, context, tool_withheld, tool, answered, succeeded,
    # failed, cancelled
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class LLMRun(Base, WorkspaceScopedMixin):
    """One piece of work a language model did for LEKA (LEKA-429): for what,
    about what, how it ended — succeeded, invalid, no_model, timed_out,
    failed — who answered (provider, model, version), the calls it took and
    their tokens and cost, how long, the LEKA context it was given. Its
    calls: model_calls.run_id."""

    __tablename__ = "llm_runs"
    __table_args__ = (Index("ix_llm_runs_workspace_started", "workspace_id", "started_at"),)

    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # The LEKA context it was given: where it was read, how many items.
    context_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    context_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelAsk(Base, WorkspaceScopedMixin):
    """What LEKA already asked a model about one thing, for one purpose,
    and on which facts (their digest) — asked again only once they changed:
    a background task never pays twice for the same question, answered or
    left out."""

    __tablename__ = "model_asks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "purpose", "key", name="uq_model_asks_purpose_key"),
    )

    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    # The model said something of it; else it left it out.
    answered: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CapabilityRouting(Base, WorkspaceScopedMixin):
    """Where an intention was routed (LEKA-398), and why: what the router
    read of it, the outcome — routed, fallback, clarify — what it selected,
    every candidate with its signals and score, every one left out with
    why. Kept as decided: routed again, a new row."""

    __tablename__ = "capability_routings"
    __table_args__ = (
        CheckConstraint("outcome IN ('routed', 'fallback', 'clarify')", name="outcome"),
        CheckConstraint("subject_type IN ('intention', 'request')", name="subject_type"),
        Index("ix_capability_routings_subject", "workspace_id", "subject_id", "at"),
    )

    # An intention, or words asked of the router alone.
    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    selected: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    # What the router read: goal, kind, mode, types, words, its context.
    query: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Candidates, excluded, background, fallback, why, questions, suggestions.
    decision: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    routed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowRun(Base, WorkspaceScopedMixin):
    """One run of a workflow (LEKA-397): which, which version, asked by whom
    with what, for which intention — where it stands, how it ended, which
    step stopped it, how many times it was retried. Its steps are
    workflow_run_steps; what happened, workflow_run_events."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="status"
        ),
        Index("ix_workflow_runs_workspace_queued", "workspace_id", "queued_at"),
        UniqueConstraint("workspace_id", "id", name="uq_workflow_runs_workspace_id_id"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    # Its steps as they were when it was asked: what it runs, whatever the
    # file says since.
    spec: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    inputs: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    intention_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Why it failed: a step's failure (`failed_step`), not permitted, gone,
    # abandoned, error.
    error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failed_step: Mapped[str | None] = mapped_column(String(60), nullable=True)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowRunStep(Base, WorkspaceScopedMixin):
    """One step of a workflow run: where it stands — pending, running,
    succeeded, failed, skipped, not reached — how many attempts, what it
    found, why it was skipped or failed."""

    __tablename__ = "workflow_run_steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["workflow_runs.workspace_id", "workflow_runs.id"],
            ondelete="CASCADE",
            name="fk_workflow_run_steps_run",
        ),
        UniqueConstraint("run_id", "step", name="uq_workflow_run_steps_step"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'not_reached')",
            name="status",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step: Mapped[str] = mapped_column(String(60), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    uses: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # skipped: condition_false · not_reached: stopped · failed: the error.
    reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # What it found: codes, a summary, what it refers to (an agent run).
    output: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowRunEvent(Base, WorkspaceScopedMixin):
    """What happened in a workflow run, in order: queued, started, a step
    started, retried, ended, skipped — the run ended, retried, cancelled.
    Append-only: the database refuses to change one."""

    __tablename__ = "workflow_run_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["workflow_runs.workspace_id", "workflow_runs.id"],
            ondelete="CASCADE",
            name="fk_workflow_run_events_run",
        ),
        Index("ix_workflow_run_events_run", "run_id", "at", "seq"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    step: Mapped[str | None] = mapped_column(String(60), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class SkillRun(Base, WorkspaceScopedMixin):
    """One run of a skill (LEKA-396), whatever came of it: which skill, which
    version and contract (its fingerprint), called by what (the analyst, the
    API, an agent) about what (`intention:<id>`…), for whom, given what —
    what it gave, or why not, and how long it took."""

    __tablename__ = "skill_runs"
    __table_args__ = (
        CheckConstraint("status IN ('succeeded', 'refused', 'failed', 'timed_out')", name="status"),
        Index("ix_skill_runs_workspace_at", "workspace_id", "at"),
        Index("ix_skill_runs_workspace_ref", "workspace_id", "ref", "at"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    # None: no such skill, or no such version.
    version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    # Refused: not_found, not_runnable, not_permitted, invalid_input,
    # unknown. Failed: invalid_output, error.
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    caller: Mapped[str] = mapped_column(String(100), nullable=False)
    ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    run_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    inputs: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # What it gave, but what it cited; none past OUTPUT_KEPT (detail.size).
    output: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # Its errors, its message, how many things it read, its size; that the
    # version run is deprecated.
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeChange(Base, WorkspaceScopedMixin):
    """A change to a repository's code an agent proposed (code-change): the
    files as they would be, each with its diff against the branch it was
    read from — for a person to accept or reject. Accepted, LEKA opens a
    pull request on the source's repository, when its admin allowed it;
    never a merge."""

    __tablename__ = "code_changes"
    __table_args__ = (
        CheckConstraint("status IN ('proposed', 'rejected', 'applied', 'failed')", name="status"),
        Index("ix_code_changes_workspace_intention", "workspace_id", "intention_id"),
        Index("ix_code_changes_workspace_run", "workspace_id", "run_id"),
    )

    # The agent run that proposed it, the intention it answers — no foreign
    # key to intentions, capabilities sits below them.
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    intention_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    repository: Mapped[str] = mapped_column(String(200), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    # The commit the files were read at: a pull request starts from it.
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Each file: path, status (added, modified, deleted), its new text, its
    # diff, lines added and removed, why.
    files: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Applied: where.
    branch: Mapped[str | None] = mapped_column(String(250), nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Failed: why — CodeRefusedError's code, and what GitHub said.
    error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Applied, its pull request followed, read only (2026-10-20): its stage
    # (changes.stage_of), its checks, its merge, the deployment that took
    # it, when read, whether it is done.
    follow: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # Undone (2026-10-20): the change this one undoes; each time a person
    # went back to the version before it — the run started, how it went.
    reverts: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("code_changes.id", ondelete="SET NULL"), nullable=True
    )
    rollbacks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )


class Publication(Base, WorkspaceScopedMixin):
    """What LEKA proposes to send out of a run's deliverable (2026-10-18):
    tickets for a Jira project, or pages for a Confluence space — drafted
    from what the agent delivered, for a person to choose and accept.
    Accepted, LEKA creates them through the source, when its admin allowed
    it (`issues`, `pages`); never an edit, never a deletion."""

    __tablename__ = "publications"
    __table_args__ = (
        CheckConstraint("kind IN ('issues', 'pages')", name="kind"),
        CheckConstraint(
            "status IN ('drafting', 'proposed', 'applied', 'partly', 'rejected', 'failed')",
            name="status",
        ),
        Index("ix_publications_workspace_run", "workspace_id", "run_id"),
        Index("ix_publications_workspace_intention", "workspace_id", "intention_id"),
    )

    # The run it was drafted from, the intention it answers — no foreign key
    # to intentions, capabilities sits below them.
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    intention_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    # The Jira project's key, or the Confluence space's.
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Each ticket or page: id, title, body (markdown), and for a ticket its
    # kind, priority and labels.
    items: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Each item sent: its id, and the key or page Atlassian gave it — or why
    # not.
    results: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
