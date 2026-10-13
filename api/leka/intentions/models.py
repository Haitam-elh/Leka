"""Tables owned by the intentions module.

An intention is the durable record of "someone asked for this, here is what
we decided, here is who approved it". It outlives the request that created
it, because an action taken against a customer's production system must be
answerable months later (LEKA-384).

    INTENTION   what was asked — its words, its scope — by whom, where it
                stands in its lifecycle (lifecycle.py), what it is about
                as LEKA read it, its current context
    EVENT       one thing that happened to it: created, moved from one
                state to another — asked again among them — linked,
                archived — who,
                when, why. Append-only: the database refuses to change one
                (a trigger), so its history can be audited
    LINK        what it rests on and what came of it: its context, the
                findings, the entities it is about — and, as LEKA-390 to
                392 add them, its decisions, actions and outcomes

No foreign key from a link to what it names: findings are resolved and
pruned, contexts archived, and a link must still say what it was.
docs/intentions.md says why each column is here.
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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin
from leka.intentions.lifecycle import Actor, IntentionStatus

STATUSES = tuple(status.value for status in IntentionStatus)
ACTORS = tuple(actor.value for actor in Actor)
EVENT_KINDS = ("created", "moved", "linked", "unlinked", "archived", "restored")
LINK_KINDS = ("context", "finding", "entity", "decision", "action", "outcome")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Intention(Base, WorkspaceScopedMixin):
    """What someone asked LEKA, and where it stands."""

    __tablename__ = "intentions"
    __table_args__ = (
        # Target for the composite foreign keys of its events and links.
        UniqueConstraint("workspace_id", "id", name="uq_intentions_workspace_id_id"),
        CheckConstraint(_in("status", STATUSES), name="status"),
        Index("ix_intentions_workspace_updated", "workspace_id", "updated_at"),
        Index("ix_intentions_workspace_status", "workspace_id", "status"),
        Index("ix_intentions_workspace_created_by", "workspace_id", "created_by"),
    )

    # Its words, as asked; its title, the first of them unless one is given.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # What it asks for, as LEKA read it (LEKA-373): diagnose, change…
    kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # The scope it was asked with: environment, since, until, services,
    # sources — the form's, as the context engine reads it (IntentAsk).
    scope: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # What LEKA understood of it (LEKA-385): the structured intent — goal,
    # mode, actions, entities, ambiguities, each with its words — and its
    # goal alone, for lists.
    understanding: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    goal: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Whether its context can ground an analysis (LEKA-387): ready, limited,
    # blocked — the critical gaps and conflicts in the way.
    readiness: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # What its asker answered to LEKA's questions (LEKA-439): one per
    # question, the latest — read again with it every time it is understood.
    answers: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # What LEKA concluded, in a sentence, once it did (LEKA-389).
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # The context it is analysed from now (contexts.subject_id is it).
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contexts.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # How many events it has: each event's place in its history.
    events_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class IntentionEvent(Base, WorkspaceScopedMixin):
    """One thing that happened to an intention. Never updated: the database
    refuses it (trigger intention_events_append_only)."""

    __tablename__ = "intention_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            ondelete="CASCADE",
            name="fk_intention_events_intention",
        ),
        UniqueConstraint("intention_id", "sequence", name="uq_intention_events_sequence"),
        CheckConstraint(_in("kind", EVENT_KINDS), name="kind"),
        CheckConstraint(_in("actor", ACTORS), name="actor"),
        CheckConstraint("(kind = 'moved') = (to_status IS NOT NULL)", name="moved_says_where"),
        Index("ix_intention_events_intention", "intention_id", "sequence"),
    )

    intention_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Its place in the intention's history: 1, 2, 3…
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # A move's name in the lifecycle: approved, failed, asked_again…
    name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    actor: Mapped[str] = mapped_column(String(10), nullable=False)
    # The person, when a person did it.
    by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # What else it says: the scope asked, the link made, the context
    # version, the error's type.
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class IntentionLink(Base, WorkspaceScopedMixin):
    """What an intention rests on, or what came of it."""

    __tablename__ = "intention_links"
    # What refers to an entity: hidden with it (LEKA-402).
    __entity_refs__ = ("ref_id",)
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            ondelete="CASCADE",
            name="fk_intention_links_intention",
        ),
        UniqueConstraint("intention_id", "kind", "ref_id", name="uq_intention_links_ref"),
        CheckConstraint(_in("kind", LINK_KINDS), name="kind"),
        Index("ix_intention_links_ref", "workspace_id", "kind", "ref_id"),
    )

    intention_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # What it was when linked — its name, and a context's version — so the
    # link still says it when the thing is gone.
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    linked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


ANALYSIS_STATUSES = ("running", "complete", "partial", "inconclusive", "failed", "blocked")
ANALYSIS_TRIGGERS = ("created", "asked_again", "requested", "sweep")


class IntentionAnalysis(Base, WorkspaceScopedMixin):
    """One analysis of an intention (LEKA-388): the capabilities chosen and
    why, what each did — succeeded, failed, timed out, skipped — and the
    result, shaped for the decision interface, every piece of evidence with
    where it came from. One per run: asked again, it is analysed again,
    the earlier kept."""

    __tablename__ = "intention_analyses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            ondelete="CASCADE",
            name="fk_intention_analyses_intention",
        ),
        UniqueConstraint("intention_id", "number", name="uq_intention_analyses_number"),
        CheckConstraint(_in("status", ANALYSIS_STATUSES), name="status"),
        CheckConstraint(_in("trigger", ANALYSIS_TRIGGERS), name="trigger"),
        Index("ix_intention_analyses_intention", "intention_id", "number"),
    )

    intention_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Its place among the intention's analyses: 1, 2, 3…
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # The context it read: which, which version — no foreign key, a context
    # is archived and the analysis must still say what it read.
    context_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    context_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    readiness: Mapped[str | None] = mapped_column(String(10), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The capabilities considered: chosen, and why; or not, and why.
    selection: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # What each did: its status, how long, its error's type, why skipped.
    steps: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # The result: findings, causes, impact, uncertainties, missing,
    # confidence, support — and the evidence, each with its sources.
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # Why it could not go on: a blocked context's critical issues, the
    # error's type.
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


DECISION_STATUSES = (
    "proposed",
    "approved",
    "rejected",
    "changes_requested",
    "superseded",
)
VERDICTS = ("approve", "reject", "modify", "request_changes")
RISK_LEVELS = ("low", "medium", "high", "critical")


class IntentionDecision(Base, WorkspaceScopedMixin):
    """A person's decision on what an intention asks to do (LEKA-390): the
    actions proposed, how risky, how many must approve under the policy in
    force, and where it stands. One per proposal: analysed again, a new one
    is opened and the earlier superseded."""

    __tablename__ = "intention_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            ondelete="CASCADE",
            name="fk_intention_decisions_intention",
        ),
        # Target for the composite foreign key of its votes.
        UniqueConstraint("workspace_id", "id", name="uq_intention_decisions_workspace_id_id"),
        UniqueConstraint("intention_id", "number", name="uq_intention_decisions_number"),
        CheckConstraint(_in("status", DECISION_STATUSES), name="status"),
        CheckConstraint(_in("risk", RISK_LEVELS), name="risk"),
        CheckConstraint("required_approvals BETWEEN 1 AND 5", name="required_approvals"),
        Index("ix_intention_decisions_intention", "intention_id", "number"),
        Index("ix_intention_decisions_queue", "workspace_id", "status", "created_at"),
    )

    intention_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Its place among the intention's decisions: 1, 2, 3…
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # The analysis that proposed it — no foreign key: the decision must say
    # what it rested on.
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    context_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Who asked: the intention's asker, kept for the four-eyes rule.
    asked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # The analysis's risk, and the one decided at — raised in production.
    analysis_risk: Mapped[str | None] = mapped_column(String(10), nullable=True)
    risk: Mapped[str] = mapped_column(String(10), nullable=False)
    # Modified: 2, 3… — the approvals of an earlier revision do not count.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False)
    separate_asker: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # The policy in force when it was opened, as kept in the settings.
    policy: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # The actions proposed, as of its revision.
    proposals: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # What the policy said of it (LEKA-404): its risk's reasons, the role one
    # approver must hold, the exceptions that froze or waived it.
    required_role: Mapped[str | None] = mapped_column(String(10), nullable=True)
    governance: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # Approved: until when the approval holds — past it, approved again.
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Waiting past its requirement's hours: when it was escalated.
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntentionDecisionVote(Base, WorkspaceScopedMixin):
    """One person's vote on a decision: approve, reject, modify, ask for
    changes — who, when, why, and the context it was cast in. Append-only:
    the database refuses to change one."""

    __tablename__ = "intention_decision_votes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "decision_id"],
            ["intention_decisions.workspace_id", "intention_decisions.id"],
            ondelete="CASCADE",
            name="fk_intention_decision_votes_decision",
        ),
        CheckConstraint(_in("verdict", VERDICTS), name="verdict"),
        Index("ix_intention_decision_votes_decision", "decision_id", "at"),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A modification: what changed, from what to what.
    changes: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # What it was cast on: the risk, the revision's proposals, the analysis
    # and context version, how many approvals were required.
    context: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Cast with another's authority, delegated (LEKA-404): whose it is.
    on_behalf_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # The role of the authority used, when it was cast.
    role: Mapped[str | None] = mapped_column(String(10), nullable=True)


# ── governance (LEKA-404) ────────────────────────────────────────────────────

EXCEPTION_KINDS = ("freeze", "waiver")
DECISION_GOVERNANCE_EVENTS = (
    "policy_changed",
    "exception_granted",
    "exception_revoked",
    "delegation_granted",
    "delegation_revoked",
    "decision_escalated",
    "decision_waived",
    "decision_frozen",
)


class GovernanceExceptionRow(Base, WorkspaceScopedMixin):
    """A freeze or a waiver an admin granted: on what, from when to when,
    why. Revoked, kept: who revoked it, when."""

    __tablename__ = "governance_exceptions"
    __table_args__ = (
        CheckConstraint(_in("kind", EXCEPTION_KINDS), name="kind"),
        CheckConstraint(_in("max_risk", RISK_LEVELS), name="max_risk"),
        CheckConstraint("ends_at > starts_at", name="window"),
        Index("ix_governance_exceptions_live", "workspace_id", "ends_at"),
    )

    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    # What it covers — a list empty: any.
    actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    environments: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    targets: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    # A waiver's: the riskiest it covers.
    max_risk: Mapped[str] = mapped_column(String(10), nullable=False, server_default="low")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ApprovalDelegation(Base, WorkspaceScopedMixin):
    """An approver's authority lent to another member: from when to when,
    up to a risk, why. Revoked, kept."""

    __tablename__ = "approval_delegations"
    __table_args__ = (
        CheckConstraint(_in("max_risk", RISK_LEVELS), name="max_risk"),
        CheckConstraint("ends_at > starts_at", name="window"),
        CheckConstraint("delegated_by <> delegated_to", name="not_oneself"),
        Index("ix_approval_delegations_to", "workspace_id", "delegated_to", "ends_at"),
    )

    delegated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    delegated_to: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    max_risk: Mapped[str] = mapped_column(String(10), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DecisionGovernanceEvent(Base, WorkspaceScopedMixin):
    """What happened to the workspace's governance: its policy changed, an
    exception or a delegation granted or revoked, a decision escalated,
    waived or frozen — who, when, on what, the detail. Append-only: the
    database refuses to change one."""

    __tablename__ = "decision_governance_events"
    __table_args__ = (
        CheckConstraint(_in("kind", DECISION_GOVERNANCE_EVENTS), name="kind"),
        Index("ix_decision_governance_events_workspace_at", "workspace_id", "at"),
    )

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # What it is about: an exception, a delegation, a decision.
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


# ── execution (LEKA-391) ─────────────────────────────────────────────────────

PLAN_STATUSES = ("planned", "scheduled", "running", "succeeded", "failed", "cancelled", "blocked")
STEP_STATUSES = ("pending", "running", "awaiting", "succeeded", "failed", "cancelled", "skipped")
EXECUTORS = ("webhook", "manual")


class ActionEndpoint(Base, WorkspaceScopedMixin):
    """A system the workspace authorized LEKA to act through (LEKA-391): its
    own automation behind an https endpoint, the actions and environments
    it accepts — LEKA calls nothing else. Its signing secret is encrypted;
    it is shown once, when made."""

    __tablename__ = "action_endpoints"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_action_endpoints_workspace_id_id"),
        UniqueConstraint("workspace_id", "name", name="uq_action_endpoints_name"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # The action codes it accepts (LEKA-385's), or "*".
    actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    # The environments it acts in, or "*".
    environments: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    # The things it may act on — none: any.
    targets: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntentionPlan(Base, WorkspaceScopedMixin):
    """What an approved decision became (LEKA-391): its steps, when it runs,
    what was checked before, how it went. A failed one is retried by a new
    plan of what did not succeed."""

    __tablename__ = "intention_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            ondelete="CASCADE",
            name="fk_intention_plans_intention",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "decision_id"],
            ["intention_decisions.workspace_id", "intention_decisions.id"],
            ondelete="CASCADE",
            name="fk_intention_plans_decision",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_intention_plans_workspace_id_id"),
        UniqueConstraint("intention_id", "number", name="uq_intention_plans_number"),
        CheckConstraint(_in("status", PLAN_STATUSES), name="status"),
        Index("ix_intention_plans_intention", "intention_id", "number"),
        Index("ix_intention_plans_due", "status", "scheduled_for"),
    )

    intention_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    # The decision's revision it carries out.
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Its windows and deadlines are read in this zone.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The checks before it ran — each code, passed or not, what it read.
    checks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # What should be true once it ran (LEKA-392): set before it runs.
    expectations: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )


class IntentionPlanStep(Base, WorkspaceScopedMixin):
    """One action of a plan: what, on what, where, who runs it, how it
    went — and the evidence of it: what was sent, what answered, who
    confirmed."""

    __tablename__ = "intention_plan_steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "plan_id"],
            ["intention_plans.workspace_id", "intention_plans.id"],
            ondelete="CASCADE",
            name="fk_intention_plan_steps_plan",
        ),
        UniqueConstraint("plan_id", "position", name="uq_intention_plan_steps_position"),
        CheckConstraint(_in("status", STEP_STATUSES), name="status"),
        CheckConstraint(_in("executor", EXECUTORS), name="executor"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    targets: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    environment: Mapped[str | None] = mapped_column(String(60), nullable=True)
    constraints: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    executor: Mapped[str] = mapped_column(String(20), nullable=False)
    # No foreign key: an endpoint removed, the step must still say it.
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    endpoint_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # What was sent, what answered, who confirmed — the execution's evidence.
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


class IntentionPlanEvent(Base, WorkspaceScopedMixin):
    """One thing that happened to a plan: made, checked, started, a step
    run, confirmed, failed, cancelled — who, when, what. Append-only."""

    __tablename__ = "intention_plan_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "plan_id"],
            ["intention_plans.workspace_id", "intention_plans.id"],
            ondelete="CASCADE",
            name="fk_intention_plan_events_plan",
        ),
        Index("ix_intention_plan_events_plan", "plan_id", "at"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(10), nullable=False)
    by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")


VERIFICATION_STATUSES = ("verifying", "succeeded", "partial", "failed")


class IntentionVerification(Base, WorkspaceScopedMixin):
    """Whether what ran achieved what was expected (LEKA-392): the
    expectations as they stood, what was observed of each — read again until
    met or the deadline — the verdict, who concluded it, and what the
    company's context was told."""

    __tablename__ = "intention_verifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            ondelete="CASCADE",
            name="fk_intention_verifications_intention",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "plan_id"],
            ["intention_plans.workspace_id", "intention_plans.id"],
            ondelete="CASCADE",
            name="fk_intention_verifications_plan",
        ),
        UniqueConstraint("plan_id", name="uq_intention_verifications_plan"),
        CheckConstraint(_in("status", VERIFICATION_STATUSES), name="status"),
        Index("ix_intention_verifications_due", "status", "observe_after"),
    )

    intention_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    expectations: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # Each expectation: met, not met, unknown, awaiting — what was read.
    results: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    observe_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    concluded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # What the company's context was told of it: the model operation queued.
    context_update: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
