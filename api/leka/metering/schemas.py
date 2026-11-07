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


class CreditWarningRead(BaseModel):
    """A share of this month's credits passed: when, and how much was used
    then (LEKA-463) — once a month for each."""

    threshold: int
    at: datetime
    used: float


class CreditsRead(BaseModel):
    """A workspace's AI credits this month (LEKA-430): its plan's and its
    packs', what its work on LEKA's models used, what is left — and whether
    LEKA's models are refused it once they are spent."""

    plan: Literal["free", "starter", "growth", "business", "enterprise"]
    plan_since: datetime | None = Field(description="None: Free from the start.")
    monthly: int = Field(description="The plan's credits a month.")
    packs: int = Field(description="Credits added to this month.")
    adjustments: int = Field(
        default=0,
        description="Given back or adjusted by LEKA this month (LEKA-553): in the allowance.",
    )
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
    warned: list[CreditWarningRead] = Field(
        default_factory=list, description="The shares passed this month, each when (LEKA-463)."
    )


class CreditPlanRead(BaseModel):
    """A plan as an AI capacity prompt shows it (LEKA-527): its credits a
    month and what it costs on the cadence asked — from metering and the
    catalogue, as checkout would charge it; nothing stated of its own."""

    key: str
    name: str
    credits: int | None = Field(description="Its AI credits a month; None: per contract.")
    self_service: bool = Field(description="Bought in LEKA; else through LEKA's sales.")
    interval: Literal["month", "year"] | None = Field(
        description="The cadence its price is for: the subscription's; None: no price."
    )
    monthly: int | None = Field(description="What it comes to a month, in cents, discounts in.")
    list_monthly: int | None = Field(description="Its list price a month, in cents.")
    charged: int | None = Field(description="What is charged each period, in cents.")
    discount: Literal["annual", "launch"] | None = None
    percent: int = Field(default=0, description="The discount's percentage.")
    for_months: int | None = Field(default=None, description="A launch price: for how long.")


class CreditPromptRead(BaseModel):
    """What the application offers a person as a workspace's AI credits run
    out (LEKA-527): past 90 % or 100 % of the month's, where it stands, what
    happens next, and the plan that gives more — or, when there is none to
    buy, when the credits come back and whom to ask. Never blocking, never
    a promise of credits before the plan is paid and applied."""

    threshold: int = Field(description="The share passed: 90 or 100.")
    used: float
    allowance: int
    remaining: float
    percent: float
    period_start: datetime
    period_end: datetime = Field(description="When the month's credits come back.")
    enforced: bool = Field(description="Spent, LEKA's models are refused until then.")
    current: CreditPlanRead
    recommended: CreditPlanRead | None = Field(
        description="The next plan with more credits; None: none above, or a contract."
    )
    more_credits: int | None = Field(description="What the recommended plan adds a month.")
    more_monthly: int | None = Field(
        description="What it adds a month on the same cadence, in cents: the year's "
        "price with its discount, the month's list price (never a launch offer's)."
    )
    currency: str = Field(description="The catalogue's currency, every price's.")
    path: Literal["upgrade", "sales", "contract"] = Field(
        description="upgrade: buy the recommended plan; sales: talk to LEKA's sales for it; "
        "contract: a contract or the highest plan — the date the credits come back, and "
        "whom to ask."
    )
    contact_url: str = Field(description="Where LEKA's sales and support are reached.")
    can_pay: bool = Field(description="Whether the reader may change the plan.")
    asked: bool = Field(
        default=False, description="Whether the reader already asked an admin, this month."
    )


class CreditPromptChoice(BaseModel):
    """A prompt put aside, or an admin asked — for the threshold seen."""

    model_config = {"extra": "forbid"}

    threshold: int
