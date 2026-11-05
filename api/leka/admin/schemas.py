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

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
# the last 30 days.
UserStatus = Literal["unverified", "new", "active", "inactive"]


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


class UserDetail(UserRow):
    company: str | None
    job_title: str | None
    company_size: str | None
    language: str | None
    region: str | None
    agent_runs: int
    credits_used_30d: float | None = Field(description="Null: no cost LEKA could measure.")
    last_active_at: datetime | None
    sign_ins: list[datetime] = Field(description="The latest sign-ins, the latest first.")


class AdminIntentionRow(BaseModel):
    id: uuid.UUID
    organisation: OrganisationRef
    created_by: PersonRef | None
    title: str | None
    kind: str | None
    status: str = Field(description="LEKA's own status, one of twelve.")
    admin_status: AdminIntentionStatus
    created_at: datetime
    status_changed_at: datetime | None
    agents: list[str]
    duration_ms: int | None = Field(description="Asked to its end; null while it runs.")
    credits: float | None = Field(description="What its work cost, in credits; null: not measured.")


class AdminTimelineEntry(BaseModel):
    at: datetime
    kind: str
    name: str | None
    from_status: str | None
    to_status: str | None
    actor: str | None
    reason: str | None


class AdminRunRow(BaseModel):
    id: uuid.UUID
    key: str
    version: str | None
    status: str
    model: str | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None


class AdminIntentionContent(BaseModel):
    """What the customer wrote and what LEKA understood: shown only to a role
    with `intentions:content`, each reading kept in the admin trail."""

    text: str
    summary: str | None
    goal: str | None
    understanding: dict[str, object] | None
    deliverables: dict[str, str] = Field(
        description="Each run's deliverable, by run id, cut at 4,000 characters."
    )


class AdminIntentionDetail(AdminIntentionRow):
    timeline: list[AdminTimelineEntry]
    runs: list[AdminRunRow]
    analyses: int
    decisions: int
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


class OrganisationAction(BaseModel):
    organisation_id: uuid.UUID
    action: str
    status: str
    done_at: datetime
    replayed: bool = Field(
        description="True: this Idempotency-Key was already answered; nothing was done again."
    )
    credits: CreditsState | None = None


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
