"""Tables owned by the capabilities module.

The catalogue's history (LEKA-393), LEKA's and no customer's: every version
of every capability ever registered — what it was (its fingerprint), where
it stood in its lifecycle — and every event of that history, append-only.
And each workspace's say on them: enabled or not, and its people's
favourites. And every run of an agent, with its steps (LEKA-395).

Agents themselves are never stored here. They are files in agents/
(architecture rule 8); what is kept is that they were registered, as what.
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


class ModelCall(Base, WorkspaceScopedMixin):
    """One call to a language model: for what, about what, to whom — the
    provider, the model, the version it said — what it cost, how long; or
    why it failed. What answers « why did LEKA say that? » and « what does
    it spend? »."""

    __tablename__ = "model_calls"
    __table_args__ = (Index("ix_model_calls_workspace_at", "workspace_id", "at"),)

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
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRun(Base, WorkspaceScopedMixin):
    """One run of an agent (LEKA-395): which agent, which version, asked by
    whom with what, on which context — where it stands, what it delivered,
    which model answered, or why it failed. Its steps are its events."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="status"
        ),
        Index("ix_agent_runs_workspace_queued", "workspace_id", "queued_at"),
        UniqueConstraint("workspace_id", "id", name="uq_agent_runs_workspace_id_id"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
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
