"""Types crossing the boundary of the metering module (LEKA-430)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TokensStatus = Literal["measured", "partial", "unknown", "none"]
CostStatus = Literal["estimated", "partial", "unknown", "none"]


class StepCost(BaseModel):
    """What one purpose took: an intention's reading, its analysis, an
    agent's analysis and its deck…"""

    calls: int = 0
    failed: int = 0
    invalid: int = 0
    retries: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    # Answered calls without a cost: no rate, or no usage said.
    unpriced: int = 0
    # Of cost_usd: answers not what was asked; tries past a model's first.
    invalid_cost_usd: float = 0.0
    retry_cost_usd: float = 0.0


class ExecutionCost(BaseModel):
    execution: str
    kind: str
    subject: str
    subject_version: str | None
    outcome: str
    started_at: datetime
    duration_ms: int | None
    calls: int
    retries: int
    tokens_in: int | None
    tokens_out: int | None
    tokens_status: TokensStatus
    llm_cost_usd: float | None
    cost_status: CostStatus


class IntentionCost(BaseModel):
    """What an intention cost LEKA, end to end: reading it, analysing it,
    the agents and workflows it ran — every try — at the rates in force."""

    intention_id: uuid.UUID
    executions: list[ExecutionCost]
    calls: int
    retries: int
    tokens_in: int | None
    tokens_out: int | None
    tokens_status: TokensStatus
    llm_cost_usd: float | None
    leka_cost_usd: float | None
    workspace_cost_usd: float | None
    cost_status: CostStatus
    steps: dict[str, StepCost] = Field(default_factory=dict)
    # What LEKA does not measure, said.
    embedding_cost: str = "not_applicable"
    tool_cost: str = "unavailable"
    infra_cost: str = "unavailable"


class CreditsRead(BaseModel):
    """A workspace's AI credits this month (LEKA-430): its plan's and its
    packs', what its work on LEKA's models used, what is left — and whether
    LEKA's models are refused it once they are spent."""

    plan: Literal["free", "starter", "growth", "business", "enterprise"]
    plan_since: datetime | None = Field(description="None: Free from the start.")
    monthly: int = Field(description="The plan's credits a month.")
    packs: int = Field(description="Credits added to this month.")
    allowance: int
    used: float
    remaining: float
    percent: float = Field(description="Of the allowance used, 0 to 100 and past.")
    period_start: datetime
    period_end: datetime
    state: Literal["ok", "warning", "exhausted"]
    warn_at: list[int] = Field(description="The percentages past which owners and admins are told.")
    enforced: bool = Field(description="Spent, LEKA's models are refused until the month ends.")
    credit_usd: float = Field(description="What a credit is worth of LEKA's model cost.")
