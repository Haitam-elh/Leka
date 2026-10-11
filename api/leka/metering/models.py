"""The usage ledger (LEKA-430): one row per execution — an agent run, a
workflow run, the work done for an intention, a run of the LLM runtime, the
rest of a day's work for one purpose — what it took and what it cost LEKA.

Derived, never told: every row is read again from what was kept where the
work was done (model_calls and the runs), and written again whole. Reading
the same calls twice writes the same row — a call retried, a sweep run
twice, a backfill over a metered month count once. Nothing is kept here
that is not already kept there: no prompt, no answer, no error text.

What is not known is said so, never written 0: tokens measured, partly, or
not at all; a cost estimated (measured tokens at the rate in force), partly,
or unknown; and the costs LEKA does not measure — embeddings (none: context
is retrieved in the database), tools, infrastructure — said not applicable
or unavailable rather than left out.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin

KINDS = ("agent_run", "workflow_run", "intention", "llm_run", "work")
TOKENS = ("measured", "partial", "unknown", "none")
COSTS = ("estimated", "partial", "unknown", "none")


def _among(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class UsageRecord(Base, WorkspaceScopedMixin):
    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", "execution", name="uq_usage_records_execution"),
        CheckConstraint(_among("kind", KINDS), name="kind"),
        CheckConstraint(_among("tokens_status", TOKENS), name="tokens_status"),
        CheckConstraint(_among("cost_status", COSTS), name="cost_status"),
        Index("ix_usage_records_workspace_started", "workspace_id", "started_at"),
        Index("ix_usage_records_workspace_intention", "workspace_id", "intention_id"),
        Index("ix_usage_records_user_id", "user_id"),
    )

    # What it is: "agent_run:<id>", "workflow_run:<id>", "intention:<id>",
    # "llm_run:<id>", "work:<purpose>:<day>".
    execution: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    intention_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # The agent, the workflow — its version; the purpose of the rest.
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # How it ended: the run's status; for calls alone, ok or failed.
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    calls: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    # Answered, and billed, but not what was asked.
    invalid_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    # Calls past a model's first try; calls to a model past the first.
    retries: Mapped[int] = mapped_column(Integer, nullable=False)
    fallbacks: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    # Answered calls whose provider did not say what they used.
    unreported_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Of the answered calls whose usage was said; none when no call's was.
    tokens_in: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tokens_thinking: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tokens_cached: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tokens_status: Mapped[str] = mapped_column(String(10), nullable=False)

    # What the models cost, at the rates in force: LEKA's, and what a
    # workspace's own model cost it (its contract, its invoice) — apart.
    llm_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    leka_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    workspace_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_status: Mapped[str] = mapped_column(String(10), nullable=False)
    # What LEKA does not measure, said: not_applicable, unavailable.
    embedding_cost: Mapped[str] = mapped_column(String(16), nullable=False)
    tool_cost: Mapped[str] = mapped_column(String(16), nullable=False)
    infra_cost: Mapped[str] = mapped_column(String(16), nullable=False)

    # "provider/model" answered; the rates priced with; by purpose: calls,
    # tokens, cost — understanding, analysis, an agent's deck…
    models: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    rates: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    steps: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    metered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CreditWarning(Base, WorkspaceScopedMixin):
    """A share of a month's AI credits past which the workspace's owners and
    admins were told (LEKA-430) — once a month for each, whoever asks
    again."""

    __tablename__ = "credit_warnings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "period", "threshold", name="uq_credit_warnings_once"),
    )

    period: Mapped[date] = mapped_column(Date, nullable=False)
    # A percentage of the month's credits: 80, 100.
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    used: Mapped[float] = mapped_column(Float, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
