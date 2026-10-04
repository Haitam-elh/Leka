"""Tables owned by the context module (LEKA-370).

A CONTEXT is what LEKA assembled to understand one request in its company
context: what it is for (its purpose, its subject — an entity, later an
intention), what it was asked (its request: the roots, how far, through
what), and where it stands in its life. Each assembly is a VERSION — made
once, never changed — and each version holds its ELEMENTS: the entities
and relationships it was made of, as the company model said them then,
each with where it came from and why it is there.

Kept whole, not as ids: the model moves on — an entity's attributes
change, a relationship goes — and a context must say, months later, what
LEKA knew when it answered. docs/context.md says why each column is here.

Where embeddings will live, alongside the entity they describe — the
pgvector column this platform runs PostgreSQL 16 for. See
docs/adr/001-postgresql.md: keeping them in the same database means an
embedding and its entity are written in one transaction, so they cannot
disagree after a crash.
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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin


class Context(Base, WorkspaceScopedMixin):
    """One request's context: what it is for, what it asks, its life."""

    __tablename__ = "contexts"
    __table_args__ = (
        # Target for the composite foreign key in context_versions.
        UniqueConstraint("workspace_id", "id", name="uq_contexts_workspace_id_id"),
        CheckConstraint(
            "status IN ('assembling', 'assembled', 'failed', 'archived')", name="status"
        ),
        CheckConstraint("subject_type IN ('entity', 'intention', 'request')", name="subject_type"),
        CheckConstraint("current_version >= 0", name="current_version"),
        Index("ix_contexts_workspace_updated_at", "workspace_id", "updated_at"),
        Index("ix_contexts_workspace_subject", "workspace_id", "subject_type", "subject_id"),
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # Why it is assembled, in the asker's words: "why is Leka API slow?".
    purpose: Mapped[str] = mapped_column(String(2000), nullable=False, server_default="")
    # What it is the context of: an entity today, an intention (LEKA-384).
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # What it asks the model for (schemas.ContextRequest): its roots, depth,
    # relationships, environment, budget. Each version keeps its own copy.
    request: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="assembling")
    # Its latest version: 0 until one is made.
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # When it was last checked against the model, changed or not: a refresh
    # that finds nothing new makes no version, but says it looked.
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContextVersion(Base, WorkspaceScopedMixin):
    """One assembly of a context: when, from which build of the model, by
    which strategy, what it holds — or why it failed. Never changed."""

    __tablename__ = "context_versions"
    __table_args__ = (
        # Pinned to its context's workspace: a version can never hold another
        # tenant's context. And the target for context_elements' own.
        ForeignKeyConstraint(
            ["workspace_id", "context_id"],
            ["contexts.workspace_id", "contexts.id"],
            name="fk_context_versions_workspace_context",
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_context_versions_workspace_id_id"),
        UniqueConstraint("context_id", "version", name="uq_context_versions_context_version"),
        CheckConstraint("status IN ('assembled', 'failed')", name="status"),
        CheckConstraint("trigger IN ('created', 'refreshed')", name="trigger"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_context_versions_workspace_context", "workspace_id", "context_id"),
    )

    context_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Why it was made: the context's creation, or a refresh — and its reason.
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # What made it: the strategy and its version, the contract it fulfils.
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    strategy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    # From which build of the company model.
    model_built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    element_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # More was found than its budget holds: how many were left out.
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    dropped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Counted: elements by kind, by type, by source kind, by retriever.
    summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # What each retriever did (LEKA-371): found how much, in how long — or
    # failed, timed out, was skipped, and why. The others went on.
    retrieval: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # How it was ranked (LEKA-372): the policy, what was left out and why,
    # what its sources disagree on. None before.
    ranking: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # What it holds, hashed: an assembly that changes nothing is no version.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    assembled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assembled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ContextElement(Base, WorkspaceScopedMixin):
    """One thing a version holds — an entity, a relationship — as the model
    said it then: what it is, where it came from, why it is there."""

    __tablename__ = "context_elements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "version_id"],
            ["context_versions.workspace_id", "context_versions.id"],
            name="fk_context_elements_workspace_version",
            ondelete="CASCADE",
        ),
        CheckConstraint("kind IN ('entity', 'relationship')", name="kind"),
        Index("ix_context_elements_version_position", "version_id", "position"),
        # Which contexts used a thing: what a change to it touches (LEKA-374).
        Index("ix_context_elements_workspace_ref", "workspace_id", "ref_id"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # The model's id of it, and its type: a service, a depends_on.
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    # What it said then: an entity's key, name, attributes; a relationship's
    # ends, confidence, origin.
    content: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    # Where it came from: its sources, its origin — stated or inferred, by
    # which rule — its confidence, when it was seen.
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    # Why it is there: which strategy put it, from which root, how far.
    reason: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    # How relevant it was found (LEKA-371): none for a tie, or before.
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    # How it was ranked (LEKA-372): its score, its place, every signal it
    # was read from, the conflicts it is part of. None before.
    ranking: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
