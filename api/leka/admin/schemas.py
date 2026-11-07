"""The Admin API's contracts (LEKA-544): what LEKA ADMIN sends and receives.

Independent of any screen: the Android app reads them, a web app will, and
docs/admin/api.md says each in words. Lists come in the API's one envelope
(`{"data": [...], "next_cursor": ...}`), errors in its one error shape
(leka/core/errors.py). A figure LEKA does not have is null and said
unavailable, never 0.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from leka.admin.access import AdminPermission, AdminRole

# ── Signing in ───────────────────────────────────────────────────────────────


class AdminSignIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # Not length-checked beyond a ceiling: a wrong password of any length is
    # refused by the same answer, never by a 422 saying its shape was wrong.
    password: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()


class AdminMe(BaseModel):
    """Who is signed in, and what their role lets them do."""

    id: uuid.UUID
    email: str
    name: str
    role: AdminRole
    permissions: list[AdminPermission] = Field(
        description="What this admin may do; a screen shows only what is in here."
    )


class AdminSignedIn(BaseModel):
    token: str = Field(
        description=(
            "Sent as `Authorization: Bearer <token>` on every call. Shown once: "
            "kept in the device's secure storage, never in the code."
        )
    )
    expires_at: datetime = Field(description="When this session ends, whatever happens.")
    idle_minutes: int = Field(description="It also ends after this long unused.")
    admin: AdminMe


class AdminPrincipal(BaseModel):
    """Who is asking, resolved from the bearer token on every request."""

    model_config = ConfigDict(frozen=True)

    admin_id: uuid.UUID
    email: str
    name: str
    role: AdminRole
    permissions: frozenset[AdminPermission]
    session_id: uuid.UUID
    ip_prefix: str | None = None
    # False for a token renewed a moment ago, still let through for the
    # calls that left with it: it opens LEKA ADMIN, it is not renewed again.
    renewable: bool = True

    def me(self) -> AdminMe:
        return AdminMe(
            id=self.admin_id,
            email=self.email,
            name=self.name,
            role=self.role,
            permissions=sorted(self.permissions),
        )


# ── What the modules read ───────────────────────────────────────────────────

# An intention's twelve statuses (leka/intentions/lifecycle.py), as LEKA
# ADMIN's five say them (LEKA-551). docs/admin/api.md has the table.
AdminIntentionStatus = Literal["pending", "running", "completed", "failed", "cancelled"]

# A person, as LEKA ADMIN classifies them (LEKA-550), from what they did —
# never from a sign-in alone: `active` is an intention, a run or a source in
# the last 30 days; `suspended`, every organisation of theirs suspended. The
# rules, in their order: docs/admin/api.md § 5. Someone invited who has no
# account yet is an invitation (AdminInvitationRow), not a person.
UserStatus = Literal["suspended", "unverified", "new", "active", "inactive"]
# How much they use LEKA (LEKA-550): from the days they were seen in the
# product and what they did in the last 30 days, both said beside it.
ActivityLevel = Literal["none", "low", "medium", "high"]


class OrganisationRef(BaseModel):
    id: uuid.UUID
    name: str


class PersonRef(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None = None


class OrganisationRow(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    demo: bool
    plan: str = Field(description="Its plan now: the last one it was put on, Free if none.")
    created_at: datetime
    owner: PersonRef | None = Field(description="Its first owner: the address LEKA writes to.")
    country: str | None = Field(
        description="ISO 3166-1 alpha-2, as LEKA's team keeps it (LEKA-549). Null: not known."
    )
    size: str | None = Field(
        description="How many people work there, as LEKA's team keeps it. Null: not known."
    )
    size_declared: str | None = Field(
        description="The size its first owner gave when signing up: theirs, apart from `size`."
    )
    members: int
    intentions: int
    last_activity_at: datetime | None = Field(
        description="The last thing done in it (the activity journal). Null: nothing yet."
    )


class BillingState(BaseModel):
    plan: str
    interval: str | None
    status: str | None = Field(description="Stripe's word: active, trialing, past_due, canceled…")
    current_period_end: datetime | None
    cancel_at_period_end: bool
    launch_offer_used: bool
    applied_at: datetime | None


class CreditsState(BaseModel):
    period: str = Field(description="The month the figures are about, YYYY-MM.")
    plan: str
    monthly: int = Field(description="The plan's credits for the month (a contract's, Enterprise).")
    packs: int = Field(description="Credits added to the month.")
    adjustments: int = Field(
        default=0, description="Given back or adjusted by LEKA's team this month (LEKA-553)."
    )
    allowance: int
    used: float
    remaining: float
    state: Literal["ok", "warning", "exhausted"]


class OrganisationCounts(BaseModel):
    members: int
    pending_invitations: int
    intentions: int
    intentions_completed: int
    intentions_failed: int
    agent_runs: int
    agent_runs_failed: int
    sources: int
    sources_in_error: int
    active_users_30d: int
    analyses_completed: int = Field(description="Ended with a result, whole or in part.")
    analyses_failed: int
    alerts_open: int = Field(description="Alerts on its environment still open (monitoring).")


class OrganisationDetail(OrganisationRow):
    default_language: str | None
    suspended_at: datetime | None
    deletion_requested_at: datetime | None
    plan_since: datetime | None
    billing: BillingState | None = Field(description="Its Stripe subscription; null: never paid.")
    credits: CreditsState
    counts: OrganisationCounts
    agents_used: list[str] = Field(description="Every agent it ran, by key.")


class MemberRow(BaseModel):
    user: PersonRef
    role: str
    since: datetime
    last_login_at: datetime | None


class InvitationRow(BaseModel):
    email: str
    role: str
    status: str
    invited_at: datetime
    expires_at: datetime


class OrganisationMembers(BaseModel):
    members: list[MemberRow]
    invitations: list[InvitationRow]


class AdminMembership(BaseModel):
    organisation: OrganisationRef
    organisation_status: str = Field(description="active, suspended or pending_deletion.")
    role: str
    since: datetime


class UserRow(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    created_at: datetime
    verified: bool
    last_login_at: datetime | None
    organisations: list[AdminMembership]
    intentions: int
    status: UserStatus
    last_active_at: datetime | None = Field(
        description="Their last intention, run or source connected. Null: none."
    )
    active_days_30d: int = Field(description="Days they were seen in the product, in 30.")
    actions_30d: int = Field(description="Intentions asked, runs, sources connected, in 30 days.")
    activity_level: ActivityLevel


class UserAccess(BaseModel):
    """What a person may do in one organisation (LEKA-550), as LEKA decides
    it on each request (governance's subject): their seat's role, a role of
    the organisation's own on it, and the permissions that leaves them."""

    organisation: OrganisationRef
    role: str
    custom_role: str | None
    permissions: list[str]


class UserDetail(UserRow):
    company: str | None
    job_title: str | None
    company_size: str | None
    language: str | None
    region: str | None
    agent_runs: int
    credits_used_30d: float | None = Field(description="Null: no cost LEKA could measure.")
    sign_ins: list[datetime] = Field(description="The latest sign-ins, the latest first.")
    access: list[UserAccess] = Field(
        description="In each organisation: their role, a role of its own, what they may do."
    )
    analyses_completed: int = Field(description="Analyses they asked that ended with a result.")
    agents_used: list[str] = Field(description="Every agent they ran, by key.")


class AdminIntentionRow(BaseModel):
    id: uuid.UUID
    organisation: OrganisationRef
    created_by: PersonRef | None
    title: str | None
    description: str | None = Field(
        description="Its summary, else the start of what was asked, cut at 200 characters; "
        "null for a role without intentions:content."
    )
    kind: str | None
    status: str = Field(description="LEKA's own status, one of twelve.")
    admin_status: AdminIntentionStatus
    created_at: datetime
    status_changed_at: datetime | None
    agents: list[str]
    duration_ms: int | None = Field(description="Asked to its end; null while it runs.")
    credits: float | None = Field(description="What its work cost, in credits; null: not measured.")


# Where a moment of an intention's story comes from (LEKA-551).
TimelineCategory = Literal[
    "intention", "analysis", "routing", "run", "decision", "action", "outcome"
]


class AdminTimelineEntry(BaseModel):
    at: datetime
    category: TimelineCategory
    kind: str
    subject: str | None = Field(description="The agent or the capability it is about.")
    ref: str | None = Field(
        description="The execution it belongs to: `run:<id>`, `analysis:<id>`, "
        "`routing:<id>`, `decision:<id>`, `plan:<id>`."
    )
    from_status: str | None
    to_status: str | None
    actor: str | None = Field(description="person or system.")
    by: str | None = Field(description="The person's name, else their address.")
    error: str | None
    reason: str | None = Field(
        description="Null for a role without intentions:content: a person may have written it."
    )


class AdminRunStep(BaseModel):
    """One step of an agent's run, as LEKA kept it: what it did, never what
    it read or wrote."""

    seq: int
    kind: str
    at: datetime
    tool: str | None
    outcome: str | None
    ms: int | None
    code: str | None = Field(description="A failure's code.")
    model: str | None
    tokens_in: int | None
    tokens_out: int | None


class AdminRunRow(BaseModel):
    id: uuid.UUID
    key: str
    version: str | None
    status: str
    model: str | None
    requested_by: PersonRef | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None
    calls: int | None = Field(description="Calls to a model; null: not measured yet.")
    failed_calls: int | None
    tokens_in: int | None
    tokens_out: int | None
    credits: float | None
    steps: list[AdminRunStep] = Field(description="At most the first 200.")


class AdminCapabilityChoice(BaseModel):
    name: str
    chosen: bool
    reason: str = Field(description="always, goal, kind, acting, no_model, disabled, not_called.")


class AdminAnalysisStep(BaseModel):
    name: str
    status: str = Field(description="succeeded, failed, timed_out, skipped.")
    duration_ms: int | None
    error: str | None
    reason: str | None


class AdminAnalysisRow(BaseModel):
    id: uuid.UUID
    number: int
    trigger: str
    status: str
    readiness: str | None
    requested_by: PersonRef | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None
    risk: str | None = Field(description="The risk its result said; null: no result.")
    confidence: float | None
    findings: int
    recommendations: int
    selection: list[AdminCapabilityChoice]
    steps: list[AdminAnalysisStep]


class AdminRoutingCandidate(BaseModel):
    key: str
    score: float | None
    eligible: bool
    selected: bool


class AdminRouting(BaseModel):
    """Which agents LEKA's router chose for it, and among which."""

    id: uuid.UUID
    at: datetime
    version: int
    outcome: str = Field(description="routed, fallback, clarify.")
    selected: list[str]
    why: str | None = Field(description="A fallback's: excluded, no_match.")
    candidates: list[AdminRoutingCandidate]
    excluded: list[str]


class AdminProposalRow(BaseModel):
    id: str
    action: str
    reversible: bool | None
    targets: int = Field(description="How many; their names are content.")


class AdminVote(BaseModel):
    verdict: str
    at: datetime
    by: PersonRef | None


class AdminDecisionRow(BaseModel):
    id: uuid.UUID
    number: int
    status: str
    risk: str
    required_approvals: int
    created_at: datetime
    decided_at: datetime | None
    proposals: list[AdminProposalRow]
    votes: list[AdminVote]


class AdminPlanStepRow(BaseModel):
    position: int
    action: str
    executor: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None


class AdminPlanRow(BaseModel):
    id: uuid.UUID
    number: int
    status: str
    scheduled_for: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    steps: list[AdminPlanStepRow]


class AdminVerificationRow(BaseModel):
    id: uuid.UUID
    status: str
    observe_after: datetime
    deadline: datetime
    observed_at: datetime | None
    concluded_at: datetime | None
    expectations: int
    results: int


ErrorSource = Literal[
    "analysis", "analysis_step", "run", "run_step", "plan", "plan_step", "model_call"
]


class AdminIntentionError(BaseModel):
    """A technical error met on its way, where it was met."""

    at: datetime = Field(description="The latest time it was met.")
    source: ErrorSource
    subject: str | None = Field(description="The agent, capability, action or model.")
    ref: str | None
    error: str
    count: int = Field(description="How many times: a model's refusals are grouped.")


class AdminWorkUsage(BaseModel):
    kind: str = Field(description="agent_run, llm_run, intention, workflow_run.")
    subject: str = Field(description="The agent, or what LEKA asked a model for.")
    executions: int
    calls: int
    tokens_in: int | None
    tokens_out: int | None
    credits: float | None


class AdminConsumption(BaseModel):
    """What its work used, from LEKA's metering: null where nothing was
    measured, never 0."""

    duration_ms: int | None
    calls: int
    failed_calls: int
    retries: int
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None = Field(description="At LEKA's rates.")
    credits: float | None
    models: list[str]
    by_work: list[AdminWorkUsage]


class AdminAnalysisResult(BaseModel):
    number: int
    answer: str | None
    summary: list[str]
    findings: list[str]
    causes: list[str]
    recommendations: list[str]
    uncertainties: list[str]
    missing: list[str]


class AdminProposalContent(BaseModel):
    decision: int = Field(description="The number of its decision.")
    id: str
    action: str
    environment: str | None
    targets: list[str]


class AdminIntentionContent(BaseModel):
    """What the customer wrote and what LEKA understood and produced: shown
    only to a role with `intentions:content`, each reading kept in the admin
    trail."""

    text: str
    summary: str | None
    goal: str | None
    understanding: dict[str, object] | None
    attachments: list[str] = Field(description="The files it was asked with, by name.")
    results: list[AdminAnalysisResult]
    proposals: list[AdminProposalContent]
    deliverables: dict[str, str] = Field(
        description="Each run's deliverable, by run id, cut at 4,000 characters."
    )


class AdminIntentionDetail(AdminIntentionRow):
    timeline: list[AdminTimelineEntry] = Field(description="Oldest first: the latest 1,000.")
    analyses: list[AdminAnalysisRow]
    routings: list[AdminRouting]
    runs: list[AdminRunRow]
    decisions: list[AdminDecisionRow]
    plans: list[AdminPlanRow]
    verifications: list[AdminVerificationRow]
    errors: list[AdminIntentionError] = Field(description="The latest first.")
    consumption: AdminConsumption
    content: AdminIntentionContent | None = Field(description="Null: this role may not read it.")


# How far an agent's cost is known (LEKA-552): every run priced at its
# providers' rates, some of them, none — or no run to price.
CostStatus = Literal["measured", "partial", "unavailable", "none"]


class AgentPrevious(BaseModel):
    """The same figures over the period just before, as long as it."""

    runs: int
    organisations: int
    success_rate: float | None
    cost_usd: float | None


class AgentStat(BaseModel):
    key: str
    title: str | None = Field(description="Its name in the registry; null: no longer there.")
    category: str | None
    version: str | None = Field(description="The registry's version today.")
    lifecycle: str | None = Field(
        description="draft, review, active, deprecated, retired; null: no longer in the registry."
    )
    runs: int
    organisations: int
    succeeded: int
    failed: int
    cancelled: int
    success_rate: float | None = Field(
        description="Succeeded out of the runs that ended; null: none ended."
    )
    average_duration_ms: int | None
    calls: int | None = Field(description="Calls to a model, as metered; null: none metered.")
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None = Field(
        description="What its runs' calls cost at the providers' rates; null: no rate known."
    )
    cost_status: CostStatus
    unpriced_runs: int = Field(description="Runs whose cost is not known: left out of cost_usd.")
    credits: float | None = Field(description="What it took of the customers' AI credits.")
    revenue_eur: float | None = Field(
        description="Monthly recurring revenue of it bought alone, coupons applied, excluding "
        "VAT; null: not bought alone, or no price known. A bundle's revenue is never split."
    )
    purchases: int = Field(description="Organisations that bought it alone, now.")
    bundle_purchases: int = Field(description="Bundles bought now that include it.")
    last_run_at: datetime | None
    previous: AgentPrevious | None = Field(
        default=None, description="Over the period just before; null: no period asked."
    )


class AgentPoint(BaseModel):
    at: datetime
    runs: int
    succeeded: int
    failed: int


class AgentModelUse(BaseModel):
    model: str | None
    runs: int
    succeeded: int
    failed: int
    success_rate: float | None
    average_duration_ms: int | None
    cost_usd: float | None


class AgentVersionUse(BaseModel):
    version: str
    runs: int
    success_rate: float | None
    first_run_at: datetime
    last_run_at: datetime


class AgentOrganisationUse(BaseModel):
    organisation: OrganisationRef
    runs: int
    succeeded: int
    failed: int
    last_run_at: datetime


class AgentFailure(BaseModel):
    error: str = Field(description="The code a run failed with.")
    runs: int
    last_at: datetime


class AgentBundle(BaseModel):
    key: str
    fr: str
    en: str


class AgentOffer(BaseModel):
    """How it is sold (LEKA-454): alone at its tier's price, in bundles, in plans."""

    tier: str | None
    monthly_price_eur: float | None = Field(description="Alone; null: not sold alone.")
    bundles: list[AgentBundle]
    included_from: str | None = Field(description="The least plan that includes it.")


class AgentRecord(BaseModel):
    """One agent over a period (LEKA-552): its figures, their days (or
    months), by model, version and organisation, its failures, its offer."""

    stat: AgentStat
    summary: str | None = Field(description="When to use it, as the registry says.")
    mode: str | None
    risk: str | None
    dedicated: bool
    offer: AgentOffer
    bucket: Literal["day", "month"]
    series: list[AgentPoint]
    models: list[AgentModelUse]
    versions: list[AgentVersionUse]
    organisations: list[AgentOrganisationUse] = Field(description="The 20 that ran it most.")
    failures: list[AgentFailure] = Field(description="The 20 most frequent.")


class OrganisationCredits(BaseModel):
    organisation: OrganisationRef
    credits: CreditsState


class AgentCost(BaseModel):
    key: str
    runs: int
    credits: float | None
    cost_usd: float | None


class ModelCost(BaseModel):
    provider: str
    model: str
    calls: int
    cost_usd: float | None


class CreditsBreakdown(BaseModel):
    organisation: OrganisationRef
    credits: CreditsState
    by_agent: list[AgentCost]
    by_model: list[ModelCost]


CreditKind = Literal["grant", "consumption", "refund", "adjustment", "expiration"]


class CreditMovement(BaseModel):
    """One line of an organisation's credits ledger (LEKA-553)."""

    id: uuid.UUID
    organisation: OrganisationRef
    kind: CreditKind
    credits: float = Field(description="Added (more than 0) or taken (less than 0).")
    period: str = Field(description="The month it counts in, YYYY-MM.")
    at: datetime
    origin: str = Field(description="plan, pack, metering, admin, close.")
    reference: str = Field(description="The operation it records, unique in the organisation.")
    execution: str | None = Field(description="A consumption's: what was metered.")
    subject: str | None = Field(description="A consumption's: the agent, or LEKA's call.")
    by: str | None = Field(description="A manual movement's author.")
    reason: str | None
    cost_usd: float | None = Field(
        description="A consumption's cost at the providers' rates, as metered."
    )
    cost_status: str | None = Field(description="estimated, partial: as the metering said it.")


class CreditSubject(BaseModel):
    subject: str
    credits: float


class CreditMonth(BaseModel):
    """One month of an organisation's credits, read from its ledger, beside
    the source: what LEKA's models cost it, as the gateway counts it."""

    period: str
    granted: float = Field(description="By the plan.")
    packs: float
    refunds: float
    adjustments: float
    consumed: float
    expired: float
    balance: float = Field(description="The sum of the month's lines.")
    source: float = Field(description="Consumed at the gateway: LEKA's models, in credits.")
    pending: float = Field(description="Consumed at the gateway, not yet in the ledger.")
    unpriced: int = Field(description="Executions LEKA could not price: no line, no guess.")
    allowance_now: int | None = Field(description="This month's allowance at the gateway.")
    allowance_gap: float | None = Field(
        description="The gateway's allowance, less the ledger's; null: a month past."
    )
    closed: bool
    reconciled: bool = Field(
        description="Nothing pending, and this month's allowance the same in both."
    )
    lines: int
    by_subject: list[CreditSubject]


class CreditReconciliation(BaseModel):
    organisation: OrganisationRef
    credits: CreditsState
    months: list[CreditMonth] = Field(description="The latest first.")


class CreditCapacity(BaseModel):
    """This month, across every organisation."""

    period: str
    organisations: int
    capacity: int = Field(description="Credits given: plans, packs, adjustments.")
    plans: int
    packs: int
    adjustments: int
    used: float
    remaining: float
    utilisation: float | None
    exhausted: int = Field(description="Organisations with nothing left.")


class CreditUse(BaseModel):
    key: str
    label: str | None
    credits: float
    cost_usd: float | None


class CreditDay(BaseModel):
    at: datetime
    credits: float


class ProviderCost(BaseModel):
    """What the models cost at the providers' rates (`model_rates`): an
    estimate from the tokens each call used, never an invoice."""

    leka_usd: float = Field(description="LEKA's models: what the credits stand for.")
    workspace_usd: float = Field(description="An organisation's own models: its own account.")
    unpriced_calls: int = Field(description="Calls with no rate known: left out, never guessed.")
    basis: Literal["rates"] = "rates"


class CreditsOverview(BaseModel):
    """AI credits across LEKA (LEKA-553): this month's capacity and balance;
    over the period, what was consumed by organisation, agent and model, day
    by day, and what it cost at the providers' rates."""

    month: CreditCapacity
    since: datetime
    until: datetime
    consumed: float
    by_organisation: list[CreditUse] = Field(description="The 20 that consumed most.")
    by_agent: list[CreditUse]
    by_model: list[CreditUse]
    series: list[CreditDay]
    provider_cost: ProviderCost


class SubscriptionDiscount(BaseModel):
    """A coupon on a subscription, as Stripe said it (LEKA-554)."""

    percent_off: float | None
    amount_off_eur: float | None
    ends: datetime | None = Field(description="Null: as long as the subscription lasts.")


class SubscriptionRow(BaseModel):
    organisation: OrganisationRef
    plan: str
    interval: str | None
    status: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    launch_offer_used: bool
    updated_at: datetime
    stripe_subscription_id: str | None
    price_eur: float | None = Field(
        description="Its list price for one interval, excluding VAT (LEKA-554)."
    )
    mrr_eur: float | None = Field(
        description="What it brings in a month now, coupon taken off, excluding VAT; null: "
        "not known; 0: it earns nothing (a trial, ended).",
    )
    discount: SubscriptionDiscount | None
    since: datetime | None = Field(description="When it started earning, as its changes say.")
    add_ons: int = Field(description="Agents or bundles bought alone, active.")


class SubscriptionAddOn(BaseModel):
    """An agent or a bundle bought alone, its own subscription (LEKA-554)."""

    key: str
    kind: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    cancel_at_period_end: bool
    mrr_eur: float | None = Field(description="Null: not known; 0: ended.")


class PlanRevenue(BaseModel):
    plan: str = Field(description="A plan, or add_ons: the agents and bundles bought alone.")
    subscriptions: int
    mrr: float
    unknown: int = Field(description="Of them, whose price is not known: left out of `mrr`.")


class InvoiceLine(BaseModel):
    description: str | None
    amount: float = Field(description="In its invoice's currency's main unit.")
    proration: bool = Field(description="Billed for a change mid-period.")
    start: datetime | None
    end: datetime | None


class InvoiceRow(BaseModel):
    """An invoice, as Stripe last said it (LEKA-554): amounts in its
    currency's main unit, its discount, tax and prorations apart."""

    id: str = Field(description="Stripe's.")
    organisation: OrganisationRef
    number: str | None
    status: str
    billing_reason: str | None
    currency: str
    subtotal: float | None
    discount: float | None
    tax: float | None
    total: float
    amount_paid: float
    amount_remaining: float
    proration: float = Field(description="What prorations billed: a plan changed mid-period.")
    period_start: datetime | None
    period_end: datetime | None
    issued_at: datetime
    paid_at: datetime | None
    attempts: int
    hosted_url: str | None = Field(description="Stripe's page of it.")
    lines: list[InvoiceLine] = Field(description="The first 50, as Stripe said them.")


class PaymentRow(BaseModel):
    id: uuid.UUID
    organisation: OrganisationRef
    outcome: Literal["succeeded", "failed"]
    amount: float
    currency: str
    invoice: str | None
    attempt: int | None
    next_attempt_at: datetime | None
    at: datetime


class RefundRow(BaseModel):
    id: uuid.UUID
    organisation: OrganisationRef
    charge: str
    invoice: str | None
    amount: float
    charged: float
    currency: str
    reason: str | None
    at: datetime


class SubscriptionChangeRow(BaseModel):
    id: uuid.UUID
    organisation: OrganisationRef
    source: Literal["plan", "add_on"]
    subscription: str
    kind: str = Field(
        description="trial, new, reactivation, upgrade, downgrade, interval, renewal_off, "
        "renewal_on, churn."
    )
    plan_before: str | None
    plan_after: str | None
    status_before: str | None
    status_after: str | None
    mrr_before_eur: float | None
    mrr_after_eur: float | None
    at: datetime


class SubscriptionDetail(BaseModel):
    """An organisation's subscriptions (LEKA-554): its plan's, its add-ons,
    every change, its latest invoices, payments and refunds."""

    subscription: SubscriptionRow
    add_ons: list[SubscriptionAddOn]
    changes: list[SubscriptionChangeRow]
    invoices: list[InvoiceRow]
    payments: list[PaymentRow]
    refunds: list[RefundRow]


class MrrMovement(BaseModel):
    count: int
    eur: float = Field(description="Its effect on the MRR, a month, excluding VAT.")
    unknown: int = Field(description="Changes whose amount is not known: left out.")


class FinanceOverview(BaseModel):
    """LEKA's finance over a period (LEKA-554), Stripe the source of truth;
    recurring revenue, billing and collection kept apart. In euros: the MRR
    excluding VAT, what was billed and collected as Stripe charged it, VAT
    included (said apart); what was said in another currency is counted
    apart, never converted."""

    since: datetime
    until: datetime
    mrr: float | None = Field(description="Now: each paying subscription's price a month.")
    arr: float | None
    mrr_start: float | None = Field(description="At the period's start, as kept each day.")
    subscriptions: int = Field(description="Paying, counted in the MRR.")
    unknown_prices: int
    trialing: int
    new: MrrMovement
    reactivations: MrrMovement
    upgrades: MrrMovement
    downgrades: MrrMovement
    churn: MrrMovement
    mrr_explained: float | None = Field(
        description="The MRR at the start and the movements: equal to `mrr` when nothing "
        "else moved it (a coupon ended, a price changed)."
    )
    mrr_gap: float | None
    by_plan: list[PlanRevenue] = Field(description="Paying subscriptions by plan.")
    invoiced: float = Field(description="Billing: the total of the invoices issued, VAT included.")
    invoiced_tax: float = Field(description="The VAT within `invoiced`.")
    invoices: int
    prorations: float
    open_invoices: int
    open_amount: float
    payments_succeeded: int
    collected: float = Field(description="Collection: what the payments took, VAT included.")
    payments_failed: int
    failed_amount: float
    refunds: int
    refunded: float
    net_collected: float = Field(description="Collected, less what refunds gave back.")
    other_currencies: int = Field(description="Amounts said in another currency: left out.")
    events: dict[str, int] = Field(description="Stripe's events of the period, by outcome.")
    failed_events: int = Field(description="Events not applied now: to look at.")
    unlinked_events: int = Field(description="Of the period, of a customer LEKA does not know.")
    last_event_at: datetime | None


class StripeEventRow(BaseModel):
    event_id: str
    type: str
    outcome: str
    received_at: datetime
    organisation: OrganisationRef | None
    detail: dict[str, object]


class SourceDiagnostic(BaseModel):
    """A source's or a read's last failure, as LEKA CORE kept it, already
    cleaned of anything secret (leka.connectors.errors.Diagnostic) — and
    scanned again before it is said (LEKA-555)."""

    code: str = Field(description="AUTH_INVALID, AUTH_EXPIRED, PERMISSION_DENIED, TIMEOUT…")
    message: str
    remediation: str | None
    retryable: bool | None
    provider_status: int | None
    detail: str | None


class SourceRow(BaseModel):
    id: uuid.UUID
    organisation: OrganisationRef
    kind: str
    name: str
    status: str
    health: str
    last_health_check_at: datetime | None
    last_error: SourceDiagnostic | None
    sync_status: str
    last_synced_at: datetime | None
    created_at: datetime


# ── Environments & integrations (LEKA-555) ───────────────────────────────────

EnvironmentState = Literal["error", "degraded", "stale", "ok", "none"]


class ConnectorUse(BaseModel):
    """A connector LEKA CORE has, and who uses it."""

    key: str
    name: str
    category: str = Field(description="code, project, docs, cloud, observability, data, chat…")
    receives: bool = Field(description="The system sends to LEKA rather than being read.")
    sources: int = Field(description="Connected with it, not disabled.")
    organisations: int
    in_error: int
    last_synced_at: datetime | None


class EnvironmentsOverview(BaseModel):
    """Every organisation's environment, together (LEKA-555); demonstration
    organisations left out."""

    organisations: int = Field(description="With a source connected, not disabled.")
    organisations_in_error: int
    sources: int = Field(description="Not disabled.")
    active: int
    in_error: int
    degraded: int
    stale: int = Field(description="Active, not read for three hours or never read.")
    disabled: int
    services: int = Field(description="Services and applications detected, not removed.")
    syncs: int = Field(description="Reads started in the last 24 hours.")
    syncs_failed: int
    last_synced_at: datetime | None
    connectors: list[ConnectorUse]


class EnvironmentRow(BaseModel):
    organisation: OrganisationRef
    state: EnvironmentState = Field(
        description="error: a source fails; degraded: one is degraded; stale: one was not "
        "read for three hours; ok; none: no source connected."
    )
    sources: int
    in_error: int
    kinds: list[str]
    last_synced_at: datetime | None
    services: int = Field(description="Services and applications detected, not removed.")
    entities: int
    relationships: int
    failed_syncs: int = Field(description="Reads that failed in the last 7 days.")


class SourceRef(BaseModel):
    id: uuid.UUID
    kind: str
    name: str


class SyncRunRow(BaseModel):
    """One read of a source, from start to end."""

    id: uuid.UUID
    source: SourceRef
    trigger: str
    status: str = Field(description="running, succeeded, failed, abandoned.")
    capability: str | None
    started_at: datetime
    finished_at: datetime | None
    records: int
    error: SourceDiagnostic | None


class EnvironmentEntity(BaseModel):
    """A thing its sources show: a service, an application, a database…"""

    id: uuid.UUID
    type: str
    name: str
    lifecycle: str
    environment: str | None
    confidence: float
    last_seen_at: datetime | None
    sources: list[SourceRef] = Field(description="The sources that show it.")


class EnvironmentRelations(BaseModel):
    """How sure LEKA is of what ties its things together."""

    confirmed: int = Field(description="Stated by a source's records, or accepted by a person.")
    supposed: int = Field(description="Inferred by a rule: never shown as certain.")
    unknown: int = Field(
        description="Services and applications tied to nothing: what they rely on is not known."
    )
    issues: int = Field(description="What the last build found wrong with a relationship.")


class EnvironmentChange(BaseModel):
    """A relationship that appeared, changed or went, at a build."""

    from_name: str
    to_name: str
    type: str
    change: str = Field(description="added, changed, removed.")
    certainty: Literal["confirmed", "supposed"] | None = Field(
        description="As it is after; none when it went."
    )
    recorded_at: datetime


class EnvironmentDetail(BaseModel):
    """An organisation's environment (LEKA-555): its sources, their reads and
    errors, what they found, how sure LEKA is of what ties it together."""

    organisation: OrganisationRef
    state: EnvironmentState
    built_at: datetime | None = Field(description="When its model was last built.")
    sources: list[SourceRow]
    syncs: list[SyncRunRow] = Field(description="The latest 20 reads.")
    failed_syncs: int = Field(description="Reads that failed in the last 7 days.")
    entities: dict[str, int] = Field(description="What was found, by type, not removed.")
    services: list[EnvironmentEntity] = Field(
        description="Its services, applications and databases: the 100 seen last."
    )
    relations: EnvironmentRelations
    history: list[EnvironmentChange] = Field(description="The latest 20 changes.")


class MapSource(BaseModel):
    """Where the map was read from, and how fresh it is."""

    id: uuid.UUID
    kind: str
    name: str
    status: str
    last_synced_at: datetime | None
    entities: int
    verified: bool = Field(description="Active, healthy and read at least once.")


class MapNode(BaseModel):
    id: str
    column: str = Field(description="code, services, data, cloud or external.")
    group: str
    kind: str
    type: str
    name: str
    status: str | None = Field(description="operational, attention, incident, unmonitored.")
    deduced: bool = Field(description="Its state is deduced from what runs it, not measured.")
    environment: str | None
    sources: list[str]
    linked: bool = Field(description="Tied to something: false, what it relies on is unknown.")


class MapLink(BaseModel):
    from_id: str
    to_id: str
    role: str
    certainty: Literal["confirmed", "supposed"] = Field(
        description="confirmed: stated by a source or accepted by a person; supposed: inferred."
    )
    origin: str = Field(description="stated, inferred or accepted.")
    rule: str = Field(description="What inferred it, or `stated`.")
    confidence: float
    sources: list[str] = Field(description="The kinds of the sources whose records state it.")
    evidence: str | None = Field(description="What says it, scanned for secrets.")


class EnvironmentMap(BaseModel):
    """An organisation's map (LEKA-555): what it runs, and only the
    relationships its collected data supports, each as certain as it is."""

    organisation: OrganisationRef
    built_at: datetime | None
    environment: str | None
    environments: list[str]
    nodes: list[MapNode]
    links: list[MapLink]
    confirmed: int
    supposed: int
    unknown: int = Field(description="Nodes tied to nothing.")
    sources: list[MapSource]
    unverified: int = Field(description="Sources not active, not healthy, or never read.")


class AdminAuditRow(BaseModel):
    id: uuid.UUID
    at: datetime
    admin_id: uuid.UUID | None
    admin_email: str | None
    action: str
    outcome: str
    target_type: str | None
    target_id: str | None
    organisation_id: uuid.UUID | None
    route: str | None
    request_id: str | None
    session_id: uuid.UUID | None = Field(description="The admin's session it was done in.")
    ip_prefix: str | None = Field(description="The network it came from, never a whole address.")
    detail: dict[str, object]


# ── Sensitive operations ─────────────────────────────────────────────────────


class ActionReason(BaseModel):
    reason: str = Field(min_length=3, max_length=300, description="Why, said to the trail.")


class CreditGrant(ActionReason):
    credits: int = Field(gt=0, le=1_000_000, description="Credits added to this month.")


class CreditAdjustment(ActionReason):
    """Credits given back or adjusted by LEKA's team in this month (LEKA-553):
    a line of the organisation's ledger, counted in its allowance at once."""

    kind: Literal["adjustment", "refund"]
    credits: int = Field(
        ge=-1_000_000,
        le=1_000_000,
        description="Added (more than 0) or taken (less than 0); a refund gives back.",
    )
    refund_of: uuid.UUID | None = Field(
        default=None, description="A refund's: the consumption it gives back, in this ledger."
    )

    @model_validator(mode="after")
    def _moves(self) -> CreditAdjustment:
        if self.credits == 0:
            raise ValueError("an adjustment moves credits")
        if self.kind == "refund" and self.credits < 0:
            raise ValueError("a refund gives credits back")
        if self.kind == "adjustment" and self.refund_of is not None:
            raise ValueError("only a refund gives a consumption back")
        return self


class OrganisationUpdate(ActionReason):
    """What LEKA's team may change about an organisation (LEKA-549): what is
    left out stays as it is."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    country: str | None = Field(
        default=None, pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2."
    )
    size: Literal["1-10", "11-50", "51-200", "201-1000", "1000+"] | None = None

    @model_validator(mode="after")
    def _something(self) -> OrganisationUpdate:
        if self.name is None and self.country is None and self.size is None:
            raise ValueError("say what changes: its name, country or size")
        return self


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def _said(cls, body: str) -> str:
        if not body.strip():
            raise ValueError("a note says something")
        return body.strip()


class NoteRow(BaseModel):
    id: uuid.UUID
    at: datetime
    admin_email: str = Field(description="Who wrote it, kept even once their account is gone.")
    admin_name: str | None
    body: str


class OrganisationHistoryRow(BaseModel):
    """What LEKA's team did to an organisation (LEKA-549): its changes, never
    what it read."""

    id: uuid.UUID
    at: datetime
    action: str
    admin_email: str | None
    detail: dict[str, object] = Field(description="Its reason, credits, what changed.")


class AlertRow(BaseModel):
    """An alert on an organisation's environment (LEKA-442), as monitoring keeps it."""

    id: uuid.UUID
    subject_type: str
    subject_name: str
    kind: str
    severity: str
    certainty: str
    status: str
    opened_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    acknowledged_at: datetime | None


class OrganisationAction(BaseModel):
    organisation_id: uuid.UUID
    action: str
    status: str
    done_at: datetime
    replayed: bool = Field(
        description="True: this Idempotency-Key was already answered; nothing was done again."
    )
    credits: CreditsState | None = None
    changed: dict[str, list[object]] | None = Field(
        default=None, description="What an update changed, as [before, after]."
    )


class ActivityRow(BaseModel):
    """One fact of the activity journal (leka/admin/activity.py)."""

    id: uuid.UUID
    kind: str
    at: datetime
    organisation_id: uuid.UUID | None
    user_id: uuid.UUID | None
    ref: str | None = Field(description="The row it was read from, as `intention:<id>`.")
    request_id: str | None
    properties: dict[str, object]


# ── Passwords and the team (LEKA-545) ────────────────────────────────────────

NEW_PASSWORD = Field(min_length=14, max_length=256, description="14 characters at least.")


class AdminForgotPassword(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()


class AdminResetPassword(AdminForgotPassword):
    code: str = Field(min_length=8, max_length=20, description="As sent by email: ABCD-EFGH.")
    password: str = NEW_PASSWORD


class AdminChangePassword(BaseModel):
    current_password: str = Field(max_length=256)
    password: str = NEW_PASSWORD


class AdminPasswordChanged(BaseModel):
    sessions_ended: int = Field(description="The admin's other sessions, ended.")


class AdminRead(BaseModel):
    """An admin, as the Super Admin manages them."""

    id: uuid.UUID
    email: str
    name: str
    role: AdminRole
    status: Literal["invited", "active", "disabled"]
    last_sign_in_at: datetime | None
    locked_until: datetime | None
    created_at: datetime
    created_by: str
    sessions: int = Field(description="Its sessions open now.")


class AdminInvite(AdminForgotPassword):
    name: str = Field(min_length=1, max_length=120)
    role: AdminRole


class AdminChange(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: AdminRole | None = None
    status: Literal["active", "disabled"] | None = None


class AdminSessionsEnded(BaseModel):
    sessions_ended: int


class AdminSessionRead(BaseModel):
    """One of the admin's devices signed in now (LEKA-546)."""

    id: uuid.UUID
    signed_in_at: datetime = Field(description="When this device signed in; renewals keep it.")
    last_seen_at: datetime
    expires_at: datetime = Field(description="When it ends, whatever happens.")
    device: str | None = Field(description="What the device said it was (its user agent).")
    ip_prefix: str | None
    current: bool = Field(description="True for the session of the token asking.")


class AdminSessionsRead(BaseModel):
    sessions: list[AdminSessionRead]


class AdminPermissionRead(BaseModel):
    permission: AdminPermission
    module: str
    level: Literal["read", "write", "sensitive"]
    grantable: bool = Field(description="False: a Super Admin's alone, never given to a role.")


class AdminRoleRead(BaseModel):
    role: AdminRole
    editable: bool = Field(description="False for super_admin: it may do everything, always.")
    permissions: list[AdminPermission]


class AdminRolesRead(BaseModel):
    roles: list[AdminRoleRead]
    permissions: list[AdminPermissionRead]


class AdminRolePermissionsUpdate(BaseModel):
    permissions: list[AdminPermission]


class AdminInvitationRow(BaseModel):
    """Someone invited to an organisation (LEKA-550): « invité » until they accept."""

    id: uuid.UUID
    email: str
    organisation: OrganisationRef
    role: str
    invited_at: datetime
    expires_at: datetime
    expired: bool
    has_account: bool = Field(description="True: the address already has a LEKA account.")


# ── Incidents & notifications (LEKA-556) ─────────────────────────────────────

IncidentCategory = Literal[
    "intention_failed",
    "agent_failed",
    "api_error",
    "integration_disconnected",
    "sync_failed",
    "credits",
    "payment_failed",
    "platform",
]
Severity = Literal["critical", "high", "medium", "low"]
IncidentStatus = Literal["new", "in_progress", "resolved", "closed"]
NotificationKind = Literal[
    "critical_incident",
    "payment_failed",
    "integration_disconnected",
    "repeated_errors",
    "capacity_near_limit",
    "abnormal_consumption",
]


class IncidentAssignee(BaseModel):
    id: uuid.UUID
    name: str
    email: str


class IncidentRow(BaseModel):
    """A problem LEKA's team must see: said as INC-<number>."""

    id: uuid.UUID
    number: int
    organisation: OrganisationRef | None = Field(description="None: the platform itself.")
    category: IncidentCategory
    severity: Severity
    status: IncidentStatus
    technical_id: str | None = Field(
        description="LEKA CORE's own id of what it is about: an intention, an agent run, a "
        "source, an invoice, a request, a rule."
    )
    detail: dict[str, object] = Field(description="Names and codes, never a secret.")
    occurrences: int
    recurring: bool = Field(description="Three times in a day: its severity raised once.")
    first_seen_at: datetime
    last_seen_at: datetime
    assignee: IncidentAssignee | None
    resolved_at: datetime | None
    closed_at: datetime | None


class IncidentEventRow(BaseModel):
    id: uuid.UUID
    kind: Literal["opened", "occurred", "recurring", "assigned", "status", "note", "auto_resolved"]
    at: datetime
    by: str | None = Field(description="The admin's address; none: LEKA, its watch.")
    detail: dict[str, object]


class IncidentRecord(BaseModel):
    incident: IncidentRow
    previous_id: uuid.UUID | None = Field(description="The same problem's incident before.")
    previous_number: int | None
    history: list[IncidentEventRow] = Field(description="The latest first.")


class IncidentSummary(BaseModel):
    """The open incidents (new, in progress), counted."""

    open: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    by_category: dict[str, int]
    unassigned: int
    recurring: int


class IncidentChange(BaseModel):
    """Taken up, resolved, closed or taken up again; given to someone (null:
    to no one); a note. One at least."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["in_progress", "resolved", "closed"] | None = None
    assignee_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def _said(cls, note: str | None) -> str | None:
        return note.strip() or None if note is not None else None

    @model_validator(mode="after")
    def _something(self) -> IncidentChange:
        if not ({"status", "assignee_id"} & self.model_fields_set) and not self.note:
            raise ValueError("a change says what changes")
        return self


class AdminNotificationRow(BaseModel):
    id: uuid.UUID
    kind: NotificationKind
    severity: Severity
    at: datetime
    organisation: OrganisationRef | None
    incident_id: uuid.UUID | None
    incident_number: int | None
    detail: dict[str, object]
    read_at: datetime | None = Field(description="When this admin read it; none: unread.")


class NotificationsRead(BaseModel):
    """Read: these, or every one not read yet."""

    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    every: bool = False

    @model_validator(mode="after")
    def _which(self) -> NotificationsRead:
        if not self.ids and not self.every:
            raise ValueError("say which, or every one")
        return self


class NotificationsCount(BaseModel):
    unread: int
    marked: int | None = Field(default=None, description="How many were marked read.")
