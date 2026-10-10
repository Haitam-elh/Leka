"""Tables owned by the governance module.

The audit trail. Append-only by intent: a row is written when something
happens and never updated, because an audit log that can be edited is not
an audit log.

LEKA-402: the entities an admin restricted, and every access decision worth
keeping — each refusal, each write or run allowed — append-only, the
database refusing to change one.

LEKA-406: the workspace's AI controls, and every outcome of one —
append-only too.

LEKA-407: the audit trail itself — one record per event that matters, in
one shape whatever produced it; and how long the workspace keeps it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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


class EntityRestriction(Base, WorkspaceScopedMixin):
    """An entity of the company model only the workspace's administrators
    see (LEKA-402): hidden everywhere from anyone else — the entity, what
    refers to it — said why, by whom, since when."""

    __tablename__ = "entity_restrictions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "entity_id", name="uq_entity_restrictions_entity"),
    )

    # No foreign key: governance sits below knowledge; an entity removed
    # from the model leaves a restriction that hides nothing.
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    restricted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    restricted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessDecision(Base, WorkspaceScopedMixin):
    """One access decision kept (LEKA-402): who asked to do what, on what,
    whether it was allowed, by which rule and why — every refusal, every
    write and every run allowed. Append-only: the database refuses to change
    one."""

    __tablename__ = "access_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('allow', 'deny')", name="decision"),
        Index("ix_access_decisions_workspace_at", "workspace_id", "at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # A permission (workspace:update…) or an action under one (agent:run…).
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    permission: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision: Mapped[str] = mapped_column(String(5), nullable=False)
    # workspace, role, owner, restriction — and the reason it gave.
    rule: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    # The role it was decided for, then.
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    route: Mapped[str | None] = mapped_column(String(200), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class WorkspaceRole(Base, WorkspaceScopedMixin):
    """A role of the workspace's own (LEKA-403): a base role — member or
    admin — with the permissions it adds and those it takes away."""

    __tablename__ = "workspace_roles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_workspace_roles_key"),
        UniqueConstraint("workspace_id", "id", name="uq_workspace_roles_workspace_id_id"),
        CheckConstraint("base IN ('member', 'admin')", name="base"),
    )

    key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base: Mapped[str] = mapped_column(String(10), nullable=False)
    added: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    removed: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class RoleAssignment(Base, WorkspaceScopedMixin):
    """A person given a role of the workspace's own (LEKA-403) — on the
    base role their seat already has."""

    __tablename__ = "role_assignments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_role_assignments_user"),
        ForeignKeyConstraint(
            ["workspace_id", "role_id"],
            ["workspace_roles.workspace_id", "workspace_roles.id"],
            ondelete="CASCADE",
            name="fk_role_assignments_role",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class WorkspacePolicy(Base, WorkspaceScopedMixin):
    """A rule of the workspace (LEKA-403): for these actions, these roles,
    these resources — refuse, or allow by exception — at this priority."""

    __tablename__ = "workspace_policies"
    __table_args__ = (
        CheckConstraint("effect IN ('deny', 'allow')", name="effect"),
        CheckConstraint("priority >= 0 AND priority <= 100", name="priority"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    effect: Mapped[str] = mapped_column(String(5), nullable=False)
    actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    # resource_types, risk_at_least, kinds, categories
    conditions: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class GovernanceEvent(Base, WorkspaceScopedMixin):
    """A change to the workspace's roles or policies (LEKA-403): what, who,
    when, before and after. Append-only: the database refuses to change one;
    who did it is forgotten with their account."""

    __tablename__ = "governance_events"
    __table_args__ = (
        # ai_control: an AI control (LEKA-406); protection: the workspace's data
        # protection policy (LEKA-405).
        CheckConstraint(
            "subject_type IN ('role', 'policy', 'assignment', 'ai_control', 'protection')",
            name="subject_type",
        ),
        Index("ix_governance_events_workspace_at", "workspace_id", "at"),
    )

    subject_type: Mapped[str] = mapped_column(String(12), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # created, updated, deleted, assigned, unassigned
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    before: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class AIControl(Base, WorkspaceScopedMixin):
    """A control on the workspace's AI (LEKA-406): what kind — model access,
    usage limit, output check, approval — over which work and which roles,
    with its kind's own settings (governance/ai.py)."""

    __tablename__ = "ai_controls"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('model_access', 'usage_limit', 'output_check', 'approval')", name="kind"
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    purposes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AIControlEvent(Base, WorkspaceScopedMixin):
    """What an AI control did, once (LEKA-406): which, to what work — its
    purpose, what it was about, the run — for whom, on which model; what it
    found, never the text itself. Append-only: the database refuses to change
    one; the person is forgotten with their account."""

    __tablename__ = "ai_control_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('refused', 'limited', 'redacted', 'blocked', 'flagged', 'held',"
            " 'approved', 'rejected')",
            name="outcome",
        ),
        Index("ix_ai_control_events_workspace_at", "workspace_id", "at"),
    )

    # No foreign key: a control removed leaves what it did.
    control_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    control_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class AuditEvent(Base, WorkspaceScopedMixin):
    """One thing that happened, as the audit trail keeps it (LEKA-407): who
    — a person, as which role, or LEKA itself — did what, to what, with
    what outcome, from where; never the data it touched.

    Append-only: the database refuses to change one, and to delete one but
    for the retention sweep and the workspace's own deletion. The person is
    forgotten with their account; what they did stays."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "category IN ('user', 'team', 'workspace', 'data', 'access', 'governance',"
            " 'decision', 'action', 'ai', 'audit')",
            name="category",
        ),
        CheckConstraint(
            "outcome IN ('success', 'failure', 'denied')",
            name="outcome",
        ),
        CheckConstraint("actor_type IN ('user', 'system')", name="actor_type"),
        Index("ix_audit_events_workspace_at", "workspace_id", "at"),
        Index("ix_audit_events_workspace_actor", "workspace_id", "actor_id", "at"),
        # A person forgotten with their account: found without reading it all.
        Index("ix_audit_events_actor_id", "actor_id"),
        Index("ix_audit_events_workspace_target", "workspace_id", "target_type", "target_id"),
    )

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(String(12), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(60), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # A network prefix, never a full address (identity.truncate_ip).
    ip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class AuditSettings(Base, WorkspaceScopedMixin):
    """How long the workspace keeps its audit trail (LEKA-407) — one row,
    none: the default."""

    __tablename__ = "audit_settings"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_audit_settings_workspace_id"),
        CheckConstraint("retention_days BETWEEN 90 AND 2555", name="retention_days"),
    )

    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
