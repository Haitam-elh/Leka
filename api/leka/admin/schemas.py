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


class AgentStat(BaseModel):
    key: str
    runs: int
    organisations: int
    succeeded: int
    failed: int
    cancelled: int
    success_rate: float | None = Field(
        description="Succeeded out of the runs that ended; null: none ended."
    )
    average_duration_ms: int | None
    cost_usd: float | None = Field(description="At the providers' rates; null: no rate known.")
    credits: float | None
    last_run_at: datetime | None


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


class SubscriptionRow(BaseModel):
    organisation: OrganisationRef
    plan: str
    interval: str | None
    status: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    launch_offer_used: bool
    updated_at: datetime


class StripeEventRow(BaseModel):
    event_id: str
    type: str
    outcome: str
    received_at: datetime
    organisation: OrganisationRef | None
    detail: dict[str, object]


class SourceRow(BaseModel):
    id: uuid.UUID
    organisation: OrganisationRef
    kind: str
    name: str
    status: str
    health: str
    last_health_check_at: datetime | None
    last_error: str | None
    sync_status: str
    last_synced_at: datetime | None
    created_at: datetime


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
