"""The Admin API (LEKA-544): LEKA ADMIN's routes, under /api/v1/admin.

For LEKA's team, never for a customer. Every route but sign-in takes an
admin's bearer token and a permission of its role
(leka/admin/dependencies.py); a customer's session cookie opens none of
them. docs/admin/api.md is the contract, route by route.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    Path,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin import (
    ActionError,
    ActionReason,
    ActivityEvent,
    ActivityRow,
    AdminAccount,
    AdminAuditEvent,
    AdminAuditRow,
    AdminAuth,
    AdminAuthError,
    AdminChange,
    AdminChangePassword,
    AdminForgotPassword,
    AdminIntentionDetail,
    AdminIntentionRow,
    AdminInvitationRow,
    AdminInvite,
    AdminMe,
    AdminNote,
    AdminNotification,
    AdminNotificationRow,
    AdminOverview,
    AdminPasswordChanged,
    AdminPermission,
    AdminPrincipal,
    AdminPrincipalDep,
    AdminRead,
    AdminResetPassword,
    AdminRole,
    AdminRolePermissionsUpdate,
    AdminRoleRead,
    AdminRolesRead,
    AdminSessionRead,
    AdminSessionsEnded,
    AdminSessionsRead,
    AdminSignedIn,
    AdminSignIn,
    AdminWindow,
    AgentFilters,
    AgentRecord,
    AgentSort,
    AgentStat,
    AlertRow,
    CodeError,
    CreditAdjustment,
    CreditGrant,
    CreditMovement,
    CreditReconciliation,
    CreditsBreakdown,
    CreditsOverview,
    EnvironmentDetail,
    EnvironmentMap,
    EnvironmentRow,
    EnvironmentsOverview,
    FinanceOverview,
    IdempotencyConflictError,
    Incident,
    IncidentAssignee,
    IncidentChange,
    IncidentError,
    IncidentRecord,
    IncidentRow,
    IncidentSummary,
    InvoiceRow,
    NoteCreate,
    NoteRow,
    NotificationsCount,
    NotificationsRead,
    OrganisationAction,
    OrganisationCredits,
    OrganisationDetail,
    OrganisationHistoryRow,
    OrganisationMembers,
    OrganisationRef,
    OrganisationRow,
    OrganisationUpdate,
    PasswordRefusedError,
    PaymentRow,
    Period,
    RefundRow,
    RenewalError,
    SourceRow,
    StripeEventRow,
    SubscriptionChangeRow,
    SubscriptionDetail,
    SubscriptionRow,
    SyncRunRow,
    UserDetail,
    UserRow,
    UserStatus,
    activity_query,
    activity_row,
    add_credits,
    add_note,
    adjust_credits,
    admin_audit_query,
    admin_emails,
    agent_record,
    agent_stats,
    alert_row,
    alerts_query,
    audit_apart,
    audit_record,
    change_incident,
    change_password,
    change_rows,
    changes_query,
    client_ip,
    credits_breakdown,
    credits_of,
    credits_overview,
    environment_detail,
    environment_map,
    environment_rows,
    environments_overview,
    environments_query,
    finance,
    forgot_password,
    history_query,
    history_rows,
    incident_assignees,
    incident_detail,
    incident_rows,
    incidents_query,
    incidents_summary,
    intention_detail,
    intention_rows,
    intentions_query,
    invitation_rows,
    invitations_query,
    invoice_rows,
    invoices_query,
    mark_read,
    movement_rows,
    movements_query,
    note_rows,
    notes_query,
    notification_rows,
    notifications_query,
    once,
    organisation_detail,
    organisation_members,
    organisation_rows,
    organisations_query,
    overview,
    payment_rows,
    payments_query,
    permissions_now,
    reconciliation,
    redeem_code,
    refund_rows,
    refunds_query,
    require_admin,
    route_of,
    set_suspended,
    source_rows,
    sources_query,
    stripe_event_rows,
    stripe_events_query,
    subscription_detail,
    subscription_rows,
    subscriptions_query,
    sync_run_rows,
    sync_runs_query,
    team,
    unread_count,
    update_organisation,
    user_detail,
    user_rows,
    users_query,
    window_of,
)
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.billing import (
    BillingAccount,
    BillingInvoice,
    BillingPayment,
    BillingRefund,
    StripeEvent,
    SubscriptionChange,
)
from leka.connectors import Source
from leka.core import ratelimit
from leka.core.config import settings
from leka.core.errors import ErrorCode
from leka.db import DatabaseSession, SortableField
from leka.governance import CreditTransaction
from leka.identity import DeferredEmailSender, EmailSender, User, build_email_sender
from leka.ingestion import SyncRun
from leka.intentions import Intention
from leka.monitoring import MonitoringAlert
from leka.platform import Invitation, Workspace

router = APIRouter(prefix="/admin", tags=["admin"])

SessionDep = DatabaseSession

# Stricter than the customers' sign-in: five tries a minute per address,
# twenty per network, on top of the account's own lock.
SIGN_IN_PER_ACCOUNT = ratelimit.Limit(attempts=5, window_seconds=60)
SIGN_IN_PER_IP = ratelimit.Limit(attempts=20, window_seconds=60)


# ── Signing in ───────────────────────────────────────────────────────────────


@router.post(
    "/auth/sign-in",
    response_model=AdminSignedIn,
    summary="Sign an admin in",
    responses={
        401: {"description": "Invalid email or password."},
        429: {"description": "Too many attempts."},
    },
)
async def sign_in(payload: AdminSignIn, request: Request, session: SessionDep) -> AdminSignedIn:
    """A new session for an admin of LEKA's team, as a bearer token.

    One answer for every failure: an unknown address, a wrong password, a
    disabled or locked account all read « Invalid email or password ». Each
    is kept in the admin trail with its reason.
    """
    ip = client_ip(request)
    email = payload.email
    for scope, identifier, limit in (
        ("admin-sign-in:ip", ip or "unknown", SIGN_IN_PER_IP),
        ("admin-sign-in:email", email, SIGN_IN_PER_ACCOUNT),
    ):
        verdict = await ratelimit.consume(scope, identifier, limit)
        if not verdict.allowed:
            raise ApiError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                ErrorCode.RATE_LIMITED,
                "Too many sign-in attempts. Wait a minute and try again.",
                headers={"Retry-After": str(verdict.retry_after_seconds)},
            )
    try:
        signed = await AdminAuth(session).sign_in(
            email, payload.password, user_agent=request.headers.get("user-agent"), ip_prefix=ip
        )
    except AdminAuthError as error:
        await audit_apart(
            "admin.sign_in_failed",
            admin_id=None,
            admin_email=email,
            route=route_of(request),
            ip_prefix=ip,
            detail={"reason": error.reason},
        )
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.INVALID_CREDENTIALS,
            "Invalid email or password.",
        ) from error

    audit_record(
        session,
        "admin.signed_in",
        admin_id=signed.account.id,
        admin_email=signed.account.email,
        target_type="admin_session",
        target_id=signed.session.id,
        route=route_of(request),
        ip_prefix=ip,
        session_id=signed.session.id,
    )
    return await _signed(session, signed.token, signed.session.expires_at, signed.account)


async def _signed(
    session: AsyncSession, token: str, expires_at: datetime, account: AdminAccount
) -> AdminSignedIn:
    # What the role grants now, as the Super Admin left it (LEKA-545): the
    # same list /me answers, not the role's defaults.
    permissions = await permissions_now(session, account.role)
    return AdminSignedIn(
        token=token,
        expires_at=expires_at,
        idle_minutes=settings.admin_session_idle_minutes,
        admin=AdminMe(
            id=account.id,
            email=account.email,
            name=account.name,
            role=AdminRole(account.role),
            permissions=sorted(permissions),
        ),
    )


@router.post("/auth/sign-out", status_code=status.HTTP_204_NO_CONTENT, summary="End this session")
async def sign_out(request: Request, principal: AdminPrincipalDep, session: SessionDep) -> Response:
    await AdminAuth(session).sign_out(principal, now=datetime.now(UTC))
    audit_record(
        session,
        "admin.signed_out",
        admin_id=principal.admin_id,
        target_type="admin_session",
        target_id=principal.session_id,
        route=route_of(request),
        ip_prefix=principal.ip_prefix,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=AdminMe, summary="Who is signed in")
async def me(principal: AdminPrincipalDep) -> AdminMe:
    """The admin of this token, their role and every permission it grants:
    a screen shows what is in `permissions`, and the server refuses the rest
    anyway."""
    return principal.me()


# ── Sessions: renewed, listed, closed (LEKA-546) ─────────────────────────────


@router.post(
    "/auth/renew",
    response_model=AdminSignedIn,
    summary="Renew this session: a new token, the same end",
    responses={409: {"description": "This token was renewed already."}},
)
async def renew_session(
    request: Request, principal: AdminPrincipalDep, session: SessionDep
) -> AdminSignedIn:
    """A new token for this device; the one sent ends. The session keeps the
    end it had: renewing never makes it last longer than the working day it
    was opened for. The old token still works thirty seconds, for the calls
    that left with it; shown after that, every session of the device ends."""
    try:
        renewed = await AdminAuth(session).renew(
            principal, user_agent=request.headers.get("user-agent")
        )
    except RenewalError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.CONFLICT,
            "This session was renewed already: use the new token.",
        ) from error
    audit_record(
        session,
        "admin.session_renewed",
        admin_id=principal.admin_id,
        target_type="admin_session",
        target_id=renewed.session.id,
        route=route_of(request),
        ip_prefix=principal.ip_prefix,
        detail={"family": str(renewed.session.family_id)},
    )
    return await _signed(session, renewed.token, renewed.session.expires_at, renewed.account)


@router.get("/auth/sessions", response_model=AdminSessionsRead, summary="My devices signed in now")
async def list_my_sessions(principal: AdminPrincipalDep, session: SessionDep) -> AdminSessionsRead:
    rows = await AdminAuth(session).sessions(principal)
    return AdminSessionsRead(
        sessions=[
            AdminSessionRead(
                id=row.id,
                signed_in_at=row.signed_in_at,
                last_seen_at=row.last_seen_at,
                expires_at=row.expires_at,
                device=row.user_agent,
                ip_prefix=row.ip_prefix,
                current=row.id == principal.session_id,
            )
            for row in rows
        ]
    )


@router.delete(
    "/auth/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Close one of my sessions",
    responses={404: {"description": "No open session of yours has this id."}},
)
async def end_my_session(
    session_id: uuid.UUID, request: Request, principal: AdminPrincipalDep, session: SessionDep
) -> Response:
    """Another of my devices signed out from this one, or this one itself."""
    if not await AdminAuth(session).end_session(principal, session_id):
        raise _not_found("open session of yours")
    audit_record(
        session,
        "admin.signed_out" if session_id == principal.session_id else "admin.session_ended",
        admin_id=principal.admin_id,
        target_type="admin_session",
        target_id=session_id,
        route=route_of(request),
        ip_prefix=principal.ip_prefix,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Reading the modules ──────────────────────────────────────────────────────
#
# Every list: the API's envelope and its signed cursor (?cursor, ?limit up to
# 200, ?sort from the route's own list, ?order). Every detail of an
# organisation, a person or an intention is kept in the admin trail as a
# reading (`admin.viewed`); what a customer wrote, as `admin.viewed_content`.

P = AdminPermission


def _sorts(*fields: tuple[str, Any, str], default: str) -> SortCatalogue:
    return SortCatalogue(
        fields=tuple(
            SortableField(name=name, column=column, note=note) for name, column, note in fields
        ),
        default=default,
    )


ORGANISATION_SORTS = _sorts(
    ("created_at", Workspace.created_at, "small table, sorted in memory"),
    ("name", Workspace.name, "small table, sorted in memory"),
    default="created_at",
)
USER_SORTS = _sorts(
    ("created_at", User.created_at, "small table, sorted in memory"),
    ("email", User.email, "unique index"),
    default="created_at",
)
INTENTION_SORTS = _sorts(
    ("created_at", Intention.created_at, "ix_intentions_workspace_created"), default="created_at"
)
MOVEMENT_SORTS = _sorts(
    ("at", CreditTransaction.at, "ix_credit_transactions_workspace_at"), default="at"
)
SUBSCRIPTION_SORTS = _sorts(
    ("updated_at", BillingAccount.updated_at, "one row per organisation"),
    ("created_at", BillingAccount.created_at, "one row per organisation"),
    default="updated_at",
)
STRIPE_SORTS = _sorts(
    ("received_at", StripeEvent.received_at, "one row per Stripe event"), default="received_at"
)
INVOICE_SORTS = _sorts(
    ("issued_at", BillingInvoice.issued_at, "ix_billing_invoices_issued"),
    ("total", BillingInvoice.total, "a few per organisation a month"),
    default="issued_at",
)
PAYMENT_SORTS = _sorts(("at", BillingPayment.at, "ix_billing_payments_at"), default="at")
REFUND_SORTS = _sorts(("at", BillingRefund.at, "ix_billing_refunds_at"), default="at")
CHANGE_SORTS = _sorts(
    ("at", SubscriptionChange.at, "ix_billing_subscription_changes_at"), default="at"
)
INCIDENT_SORTS = _sorts(
    ("last_seen_at", Incident.last_seen_at, "ix_admin_incidents_status_seen"),
    ("first_seen_at", Incident.first_seen_at, "a few hundred at most"),
    ("number", Incident.number, "uq_admin_incidents_number"),
    default="last_seen_at",
)
NOTIFICATION_SORTS = _sorts(("at", AdminNotification.at, "ix_admin_notifications_at"), default="at")
SYNC_SORTS = _sorts(
    ("started_at", SyncRun.started_at, "ix_sync_runs_source_started_at"), default="started_at"
)
SOURCE_SORTS = _sorts(
    ("created_at", Source.created_at, "a few per organisation"),
    ("name", Source.name, "a few per organisation"),
    default="created_at",
)
AUDIT_SORTS = _sorts(("at", AdminAuditEvent.at, "ix_admin_audit_events_at"), default="at")
ACTIVITY_SORTS = _sorts(("at", ActivityEvent.at, "ix_activity_events_kind_at"), default="at")
INVITATION_SORTS = _sorts(
    ("created_at", Invitation.created_at, "a few per organisation"), default="created_at"
)
NOTE_SORTS = _sorts(
    ("created_at", AdminNote.created_at, "ix_admin_notes_workspace_created"), default="created_at"
)
ALERT_SORTS = _sorts(
    ("opened_at", MonitoringAlert.opened_at, "ix_monitoring_alerts_workspace_status"),
    default="opened_at",
)

Admin = Annotated[AdminPrincipal, Depends(require_admin(P.ORGANISATIONS_READ))]


def _viewed(
    session: AsyncSession,
    request: Request,
    principal: AdminPrincipal,
    target_type: str,
    target_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None = None,
    content: bool = False,
) -> None:
    audit_record(
        session,
        "admin.viewed_content" if content else "admin.viewed",
        admin_id=principal.admin_id,
        target_type=target_type,
        target_id=target_id,
        workspace_id=workspace_id,
        route=route_of(request),
        ip_prefix=principal.ip_prefix,
    )


def _not_found(what: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"No {what} with this id.")


@router.get("/overview", response_model=AdminOverview, summary="The figures of LEKA ADMIN's home")
async def get_overview(
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.DASHBOARD_READ))],
    period: Period = "30d",
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> AdminOverview:
    """Acquisition, activity, product, business, costs, technical and customer
    intelligence figures over `period` (today, 7d, 30d, 90d, 12m, or custom
    with `from` and `to`), the latest activity, and their series per day (per
    month past 90 days). Amounts (revenue, money collected, costs) only for a
    role that reads billing (docs/admin/indicateurs.md)."""
    try:
        window = window_of(period, start=start, end=end)
    except ValueError as error:
        raise ApiError(status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_FILTER, str(error)) from error
    return await overview(session, window, amounts=P.BILLING_READ in principal.permissions)


@router.get(
    "/organisations", response_model=PageEnvelope[OrganisationRow], summary="Every organisation"
)
async def list_organisations(
    session: SessionDep,
    _: Admin,
    page: PageParams,
    q: Annotated[
        str | None, Query(max_length=200, description="Name, slug, id or an owner's email.")
    ] = None,
    plan: str | None = None,
    organisation_status: Annotated[str | None, Query(alias="status")] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    include_demo: bool = False,
    country: Annotated[
        str | None, Query(pattern=r"^[A-Za-z]{2}$", description="ISO 3166-1 alpha-2.")
    ] = None,
    size: Annotated[
        str | None,
        Query(description="1-10, 11-50, 51-200, 201-1000, 1000+: kept by LEKA, else declared."),
    ] = None,
    activity: Annotated[
        Literal["active", "inactive", "never"] | None,
        Query(description="Something done in the last 30 days, before only, or never."),
    ] = None,
) -> PageEnvelope[OrganisationRow]:
    found = await serve_page(
        session,
        organisations_query(
            q=q,
            plan=plan,
            status=organisation_status,
            created_from=created_from,
            created_to=created_to,
            include_demo=include_demo,
            country=country,
            size=size,
            activity=activity,
        ),
        request=page,
        catalogue=ORGANISATION_SORTS,
        id_column=Workspace.id,
    )
    return PageEnvelope(
        data=await organisation_rows(session, found.items), next_cursor=found.next_cursor
    )


@router.get(
    "/organisations/{organisation_id}",
    response_model=OrganisationDetail,
    summary="An organisation, whole",
)
async def get_organisation(
    organisation_id: uuid.UUID, request: Request, session: SessionDep, principal: Admin
) -> OrganisationDetail:
    """Its information, plan, subscription, credits this month, figures and
    the agents it ran: the fiche client 360° (LEKA-549)."""
    found = await organisation_detail(session, organisation_id)
    if found is None:
        raise _not_found("organisation")
    _viewed(
        session, request, principal, "organisation", organisation_id, workspace_id=organisation_id
    )
    return found


@router.get(
    "/organisations/{organisation_id}/members",
    response_model=OrganisationMembers,
    summary="An organisation's people",
)
async def get_organisation_members(
    organisation_id: uuid.UUID, session: SessionDep, _: Admin
) -> OrganisationMembers:
    if await session.get(Workspace, organisation_id) is None:
        raise _not_found("organisation")
    return await organisation_members(session, organisation_id)


@router.get(
    "/organisations/{organisation_id}/credits",
    response_model=CreditsBreakdown,
    summary="An organisation's credits, by agent and by model",
)
async def get_organisation_credits(
    organisation_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.CREDITS_READ))],
    since: datetime | None = None,
) -> CreditsBreakdown:
    """This month's credits, and what was consumed since `since` (the start
    of the month by default), by agent and by model."""
    now = datetime.now(UTC)
    found = await credits_breakdown(
        session,
        organisation_id,
        since=since or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    )
    if found is None:
        raise _not_found("organisation")
    return found


@router.get(
    "/organisations/{organisation_id}/activity",
    response_model=PageEnvelope[ActivityRow],
    summary="What happened in an organisation",
)
async def get_organisation_activity(
    organisation_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.ACTIVITY_READ))],
    page: PageParams,
    kind: str | None = None,
) -> PageEnvelope[ActivityRow]:
    found = await serve_page(
        session,
        activity_query(organisation_id=organisation_id, kind=kind),
        request=page,
        catalogue=ACTIVITY_SORTS,
        id_column=ActivityEvent.id,
    )
    return PageEnvelope(data=[activity_row(e) for e in found.items], next_cursor=found.next_cursor)


@router.get(
    "/organisations/{organisation_id}/notes",
    response_model=PageEnvelope[NoteRow],
    summary="LEKA's internal notes about an organisation",
)
async def list_organisation_notes(
    organisation_id: uuid.UUID, session: SessionDep, _: Admin, page: PageParams
) -> PageEnvelope[NoteRow]:
    """What LEKA's team wrote down about it, the latest first (LEKA-549)."""
    if await session.get(Workspace, organisation_id) is None:
        raise _not_found("organisation")
    found = await serve_page(
        session,
        notes_query(organisation_id=organisation_id),
        request=page,
        catalogue=NOTE_SORTS,
        id_column=AdminNote.id,
    )
    return PageEnvelope(data=await note_rows(session, found.items), next_cursor=found.next_cursor)


@router.get(
    "/organisations/{organisation_id}/history",
    response_model=PageEnvelope[OrganisationHistoryRow],
    summary="What LEKA's team did to an organisation",
)
async def list_organisation_history(
    organisation_id: uuid.UUID, session: SessionDep, _: Admin, page: PageParams
) -> PageEnvelope[OrganisationHistoryRow]:
    """Suspended, reactivated, changed, credits added, a note written: by
    whom, when, why; never what was read (LEKA-549)."""
    if await session.get(Workspace, organisation_id) is None:
        raise _not_found("organisation")
    found = await serve_page(
        session,
        history_query(organisation_id),
        request=page,
        catalogue=AUDIT_SORTS,
        id_column=AdminAuditEvent.id,
    )
    return PageEnvelope(
        data=await history_rows(session, found.items), next_cursor=found.next_cursor
    )


@router.get(
    "/organisations/{organisation_id}/incidents",
    response_model=PageEnvelope[AlertRow],
    summary="The alerts on an organisation's environment",
)
async def list_organisation_incidents(
    organisation_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.ENVIRONMENTS_READ))],
    page: PageParams,
    alert_status: Annotated[
        Literal["open", "resolved", "closed"] | None, Query(alias="status")
    ] = None,
) -> PageEnvelope[AlertRow]:
    """What monitoring saw go wrong in its environment, the latest first (LEKA-549)."""
    if await session.get(Workspace, organisation_id) is None:
        raise _not_found("organisation")
    statement = alerts_query(organisation_id)
    if alert_status:
        statement = statement.where(MonitoringAlert.status == alert_status)
    found = await serve_page(
        session, statement, request=page, catalogue=ALERT_SORTS, id_column=MonitoringAlert.id
    )
    return PageEnvelope(data=[alert_row(a) for a in found.items], next_cursor=found.next_cursor)


@router.get("/users", response_model=PageEnvelope[UserRow], summary="Every person")
async def list_users(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.USERS_READ))],
    page: PageParams,
    q: Annotated[str | None, Query(max_length=200, description="Email, name or id.")] = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[
        str | None, Query(max_length=200, description="An organisation's name or slug.")
    ] = None,
    role: Annotated[
        Literal["owner", "admin", "member"] | None,
        Query(description="Their role in an organisation (the one asked, if any)."),
    ] = None,
    verified: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    active_from: Annotated[
        datetime | None, Query(description="Their last intention, run or source from then on.")
    ] = None,
    active_to: Annotated[datetime | None, Query(description="…before then.")] = None,
    never_active: Annotated[
        bool, Query(description="No intention, run nor source connected, ever.")
    ] = False,
) -> PageEnvelope[UserRow]:
    """Every person (LEKA-550): their organisations and roles, intentions,
    status and level of activity (docs/admin/api.md § 5). Someone invited
    with no account yet is in GET /admin/invitations."""
    found = await serve_page(
        session,
        users_query(
            q=q,
            organisation_id=organisation_id,
            organisation=organisation,
            role=role,
            verified=verified,
            created_from=created_from,
            created_to=created_to,
            status=user_status,
            active_from=active_from,
            active_to=active_to,
            never_active=never_active,
        ),
        request=page,
        catalogue=USER_SORTS,
        id_column=User.id,
    )
    return PageEnvelope(data=await user_rows(session, found.items), next_cursor=found.next_cursor)


@router.get("/users/{user_id}", response_model=UserDetail, summary="A person, whole")
async def get_user(
    user_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.USERS_READ))],
) -> UserDetail:
    found = await user_detail(session, user_id)
    if found is None:
        raise _not_found("person")
    _viewed(session, request, principal, "user", user_id)
    return found


@router.get(
    "/invitations",
    response_model=PageEnvelope[AdminInvitationRow],
    summary="Those invited, not yet in",
)
async def list_invitations(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.USERS_READ))],
    page: PageParams,
    q: Annotated[str | None, Query(max_length=200, description="Their email.")] = None,
    organisation_id: uuid.UUID | None = None,
    include_expired: bool = False,
) -> PageEnvelope[AdminInvitationRow]:
    """The invitations neither accepted nor revoked (LEKA-550): those
    « invités », the latest first; expired ones only when asked."""
    found = await serve_page(
        session,
        invitations_query(q=q, organisation_id=organisation_id, include_expired=include_expired),
        request=page,
        catalogue=INVITATION_SORTS,
        id_column=Invitation.id,
    )
    return PageEnvelope(
        data=await invitation_rows(session, found.items), next_cursor=found.next_cursor
    )


@router.get(
    "/users/{user_id}/notes",
    response_model=PageEnvelope[NoteRow],
    summary="LEKA's internal notes about a person",
)
async def list_user_notes(
    user_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.USERS_READ))],
    page: PageParams,
) -> PageEnvelope[NoteRow]:
    """What LEKA's team wrote down about them, the latest first (LEKA-550)."""
    if await session.get(User, user_id) is None:
        raise _not_found("person")
    found = await serve_page(
        session,
        notes_query(user_id=user_id),
        request=page,
        catalogue=NOTE_SORTS,
        id_column=AdminNote.id,
    )
    return PageEnvelope(data=await note_rows(session, found.items), next_cursor=found.next_cursor)


@router.post(
    "/users/{user_id}/notes",
    response_model=NoteRow,
    status_code=status.HTTP_201_CREATED,
    summary="Write an internal note about a person",
)
async def add_user_note(
    user_id: uuid.UUID,
    payload: NoteCreate,
    request: Request,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.USERS_NOTES))],
) -> NoteRow:
    """For LEKA's team, never shown to them (LEKA-550). The admin trail says
    one was written, never what it says."""
    try:
        return await add_note(session, principal, payload, user_id=user_id, route=route_of(request))
    except ActionError as error:
        raise _not_found("person") from error


@router.get(
    "/intentions", response_model=PageEnvelope[AdminIntentionRow], summary="Every intention"
)
async def list_intentions(
    request: Request,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.INTENTIONS_READ))],
    page: PageParams,
    q: Annotated[
        str | None, Query(max_length=200, description="Its id, or words of its title.")
    ] = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[
        str | None, Query(max_length=200, description="An organisation's name or slug.")
    ] = None,
    user_id: uuid.UUID | None = None,
    user: Annotated[
        str | None, Query(max_length=200, description="Who asked it: their address or name.")
    ] = None,
    intention_status: Annotated[
        str | None,
        Query(
            alias="status",
            description="pending, running, completed, failed, cancelled, or LEKA's own",
        ),
    ] = None,
    kind: Annotated[str | None, Query(max_length=30)] = None,
    agent: Annotated[str | None, Query(max_length=100, description="An agent's key.")] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> PageEnvelope[AdminIntentionRow]:
    """Every intention of every customer (LEKA-551): its organisation, who
    asked it, its title, its five statuses, agents, duration and credits. Its
    short description is content: only for intentions:content, and each
    page of it read is kept in the admin trail."""
    found = await serve_page(
        session,
        intentions_query(
            q=q,
            organisation_id=organisation_id,
            organisation=organisation,
            user_id=user_id,
            user=user,
            status=intention_status,
            kind=kind,
            agent=agent,
            created_from=created_from,
            created_to=created_to,
        ),
        request=page,
        catalogue=INTENTION_SORTS,
        id_column=Intention.id,
    )
    with_content = P.INTENTIONS_CONTENT in principal.permissions
    rows = await intention_rows(session, found.items, with_content=with_content)
    described = [str(r.id) for r in rows if r.description is not None]
    if described:
        audit_record(
            session,
            "admin.viewed_content",
            admin_id=principal.admin_id,
            target_type="intention",
            route=route_of(request),
            ip_prefix=principal.ip_prefix,
            detail={"read": "descriptions", "intentions": described},
        )
    return PageEnvelope(data=rows, next_cursor=found.next_cursor)


@router.get(
    "/intentions/{intention_id}",
    response_model=AdminIntentionDetail,
    summary="An intention, step by step",
)
async def get_intention(
    intention_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.INTENTIONS_READ))],
) -> AdminIntentionDetail:
    """Its whole story, oldest first; how LEKA understood it and which agents
    it chose; each run and its steps; its decisions, plans and checks; the
    errors met; what its work used (LEKA-551). What the customer wrote and
    what LEKA read or produced from it (`content`, the description, a reason)
    only for a role with intentions:content, each reading kept in the admin
    trail. Read only: nothing here acts on a customer's environment."""
    with_content = P.INTENTIONS_CONTENT in principal.permissions
    found = await intention_detail(session, intention_id, with_content=with_content)
    if found is None:
        raise _not_found("intention")
    _viewed(
        session,
        request,
        principal,
        "intention",
        intention_id,
        workspace_id=found.organisation.id,
        content=with_content,
    )
    return found


RunStatus = Literal["awaiting_approval", "queued", "running", "succeeded", "failed", "cancelled"]
Lifecycle = Literal["draft", "review", "active", "deprecated", "retired"]


def _window(period: Period, start: datetime | None, end: datetime | None) -> AdminWindow:
    try:
        return window_of(period, start=start, end=end)
    except ValueError as error:
        raise ApiError(status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_FILTER, str(error)) from error


@router.get(
    "/agents", response_model=PageEnvelope[AgentStat], summary="Every agent's use and performance"
)
async def list_agents(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.AGENTS_READ))],
    period: Annotated[
        Period | None,
        Query(
            description="today, 7d, 30d, 90d, 12m, or custom with from and to: each agent "
            "beside the period just before, as long as it."
        ),
    ] = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[
        str | None, Query(max_length=200, description="An organisation's name or slug.")
    ] = None,
    user_id: Annotated[
        uuid.UUID | None, Query(description="The runs a person asked (LEKA-550).")
    ] = None,
    agent: Annotated[str | None, Query(max_length=100)] = None,
    model: Annotated[str | None, Query(max_length=120)] = None,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
    lifecycle: Lifecycle | None = None,
    unused: Annotated[
        bool, Query(description="The registry's agents that did not run are listed too.")
    ] = False,
    sort: AgentSort = "runs",
    order: Literal["asc", "desc"] = "desc",
) -> PageEnvelope[AgentStat]:
    """One row per agent, ranked by `sort` (an unknown figure last whichever
    the order); one page. Its runs, organisations, successes, failures,
    duration, what its runs used and cost at the providers' rates (partial
    or unavailable, said so), its credits, its revenue when it is bought
    alone (LEKA-552)."""
    window = _window(period, start, end) if period else None
    return PageEnvelope(
        data=await agent_stats(
            session,
            since=window.start if window else since,
            until=window.end if window else until,
            organisation_id=organisation_id,
            organisation=organisation,
            user_id=user_id,
            agent=agent,
            model=model,
            status=run_status,
            lifecycle=lifecycle,
            unused=unused,
            compare=window is not None,
            sort=sort,
            order=order,
        )
    )


@router.get("/agents/{key}", response_model=AgentRecord, summary="One agent over a period")
async def get_agent(
    key: Annotated[str, Path(max_length=100)],
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.AGENTS_READ))],
    period: Period = "30d",
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[str | None, Query(max_length=200)] = None,
    model: Annotated[str | None, Query(max_length=120)] = None,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
) -> AgentRecord:
    """Its figures over the period and the one before; per day (per month
    beyond 92 days); by model, by version, by organisation (the 20 that ran
    it most); its 20 most frequent failures; how it is sold (LEKA-552)."""
    window = _window(period, start, end)
    found = await agent_record(
        session,
        key,
        window,
        AgentFilters(
            organisation_id=organisation_id,
            organisation=organisation,
            model=model,
            status=run_status,
        ),
    )
    if found is None:
        raise _not_found("agent")
    return found


@router.get("/credits/overview", response_model=CreditsOverview, summary="AI credits across LEKA")
async def get_credits_overview(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.CREDITS_READ))],
    period: Period = "30d",
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> CreditsOverview:
    """This month's capacity and balance across organisations; over the
    period, what was consumed by organisation, agent and model, day by day,
    and what it cost at the providers' rates (LEKA-553). Capacity, credits
    and the providers' cost are said apart."""
    return await credits_overview(session, _window(period, start, end), now=datetime.now(UTC))


@router.get(
    "/credits/movements",
    response_model=PageEnvelope[CreditMovement],
    summary="Every line of every credits ledger",
)
async def list_credit_movements(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.CREDITS_READ))],
    page: PageParams,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[
        str | None, Query(max_length=200, description="An organisation's name or slug.")
    ] = None,
    kind: Literal["grant", "consumption", "refund", "adjustment", "expiration"] | None = None,
    origin: Literal["plan", "pack", "metering", "admin", "close"] | None = None,
    period: Annotated[
        str | None, Query(pattern=r"^\d{4}-\d{2}$", description="A month, YYYY-MM.")
    ] = None,
    execution: Annotated[str | None, Query(max_length=160)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> PageEnvelope[CreditMovement]:
    """The ledger (LEKA-553): each movement with its organisation, kind,
    credits, month, date, origin, operation reference and, written by
    LEKA's team, its author and reason. The latest first by default."""
    found = await serve_page(
        session,
        movements_query(
            organisation_id=organisation_id,
            organisation=organisation,
            kind=kind,
            origin=origin,
            period=period,
            execution=execution,
            since=since,
            until=until,
        ),
        request=page,
        catalogue=MOVEMENT_SORTS,
        id_column=CreditTransaction.id,
    )
    return PageEnvelope(
        data=await movement_rows(session, found.items), next_cursor=found.next_cursor
    )


@router.get(
    "/organisations/{organisation_id}/credits/reconciliation",
    response_model=CreditReconciliation,
    summary="An organisation's credits, month by month, reconciled",
)
async def get_credit_reconciliation(
    organisation_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.CREDITS_READ))],
    months: Annotated[int, Query(ge=1, le=24)] = 6,
) -> CreditReconciliation:
    """Each month of its ledger (LEKA-553): given by the plan and the packs,
    given back and adjusted, consumed, expired, its balance — beside what
    LEKA's models cost it at the gateway: what is pending, what differs,
    what could not be priced."""
    found = await reconciliation(session, organisation_id, months=months, now=datetime.now(UTC))
    if found is None:
        raise _not_found("organisation")
    return found


@router.get(
    "/credits",
    response_model=PageEnvelope[OrganisationCredits],
    summary="Every organisation's credits",
)
async def list_credits(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.CREDITS_READ))],
    page: PageParams,
    q: Annotated[str | None, Query(max_length=200)] = None,
    plan: str | None = None,
) -> PageEnvelope[OrganisationCredits]:
    found = await serve_page(
        session,
        organisations_query(q=q, plan=plan),
        request=page,
        catalogue=ORGANISATION_SORTS,
        id_column=Workspace.id,
    )
    return PageEnvelope(
        data=[
            OrganisationCredits(
                organisation=OrganisationRef(id=w.id, name=w.name),
                credits=await credits_of(session, w.id),
            )
            for w in found.items
        ],
        next_cursor=found.next_cursor,
    )


@router.get(
    "/subscriptions",
    response_model=PageEnvelope[SubscriptionRow],
    summary="Every Stripe subscription",
)
async def list_subscriptions(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.BILLING_READ))],
    page: PageParams,
    plan: str | None = None,
    subscription_status: Annotated[str | None, Query(alias="status")] = None,
    interval: str | None = None,
    organisation: Annotated[
        str | None, Query(max_length=200, description="An organisation's name or slug.")
    ] = None,
) -> PageEnvelope[SubscriptionRow]:
    """Each organisation's plan subscription, as Stripe last said it: its
    price, what it brings in a month now, its coupon, since when it earns,
    its agents bought alone (LEKA-554)."""
    found = await serve_page(
        session,
        subscriptions_query(
            plan=plan, status=subscription_status, interval=interval, organisation=organisation
        ),
        request=page,
        catalogue=SUBSCRIPTION_SORTS,
        id_column=BillingAccount.id,
    )
    return PageEnvelope(
        data=await subscription_rows(session, found.items, now=datetime.now(UTC)),
        next_cursor=found.next_cursor,
    )


@router.get(
    "/subscriptions/{organisation_id}",
    response_model=SubscriptionDetail,
    summary="An organisation's subscriptions and their history",
)
async def get_subscription(
    organisation_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.BILLING_READ))],
) -> SubscriptionDetail:
    """Its plan's subscription, its agents bought alone, every change of
    them, its latest invoices, payments and refunds (LEKA-554)."""
    found = await subscription_detail(session, organisation_id, now=datetime.now(UTC))
    if found is None:
        raise _not_found("organisation")
    return found


@router.get("/billing/finance", response_model=FinanceOverview, summary="LEKA's finance")
async def get_finance(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.BILLING_READ))],
    period: Period = "30d",
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> FinanceOverview:
    """Recurring revenue (the MRR now, the ARR, the movements of the
    period), billing (the invoices issued), collection (the payments, the
    refunds) kept apart; Stripe's events of the period (LEKA-554). In euros:
    the MRR excluding VAT, billing and collection VAT included;
    demonstration organisations left out."""
    return await finance(session, _window(period, start, end), now=datetime.now(UTC))


@router.get("/billing/invoices", response_model=PageEnvelope[InvoiceRow], summary="Every invoice")
async def list_invoices(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.BILLING_READ))],
    page: PageParams,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[str | None, Query(max_length=200)] = None,
    invoice_status: Annotated[
        Literal["draft", "open", "paid", "uncollectible", "void"] | None, Query(alias="status")
    ] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> PageEnvelope[InvoiceRow]:
    """Each invoice as Stripe last said it, its lines, discount, tax and
    prorations apart (LEKA-554). The latest issued first by default."""
    found = await serve_page(
        session,
        invoices_query(
            organisation_id=organisation_id,
            organisation=organisation,
            status=invoice_status,
            since=since,
            until=until,
        ),
        request=page,
        catalogue=INVOICE_SORTS,
        id_column=BillingInvoice.id,
    )
    return PageEnvelope(
        data=await invoice_rows(session, found.items), next_cursor=found.next_cursor
    )


@router.get("/billing/payments", response_model=PageEnvelope[PaymentRow], summary="Every payment")
async def list_payments(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.BILLING_READ))],
    page: PageParams,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[str | None, Query(max_length=200)] = None,
    outcome: Literal["succeeded", "failed"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> PageEnvelope[PaymentRow]:
    """Each invoice paid, and each attempt that failed (LEKA-554)."""
    found = await serve_page(
        session,
        payments_query(
            organisation_id=organisation_id,
            organisation=organisation,
            outcome=outcome,
            since=since,
            until=until,
        ),
        request=page,
        catalogue=PAYMENT_SORTS,
        id_column=BillingPayment.id,
    )
    return PageEnvelope(
        data=await payment_rows(session, found.items), next_cursor=found.next_cursor
    )


@router.get("/billing/refunds", response_model=PageEnvelope[RefundRow], summary="Every refund")
async def list_refunds(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.BILLING_READ))],
    page: PageParams,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[str | None, Query(max_length=200)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> PageEnvelope[RefundRow]:
    """What each charge gave back, its refunds together (LEKA-554)."""
    found = await serve_page(
        session,
        refunds_query(
            organisation_id=organisation_id, organisation=organisation, since=since, until=until
        ),
        request=page,
        catalogue=REFUND_SORTS,
        id_column=BillingRefund.id,
    )
    return PageEnvelope(data=await refund_rows(session, found.items), next_cursor=found.next_cursor)


@router.get(
    "/billing/changes",
    response_model=PageEnvelope[SubscriptionChangeRow],
    summary="Every change of a subscription",
)
async def list_subscription_changes(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.BILLING_READ))],
    page: PageParams,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[str | None, Query(max_length=200)] = None,
    kind: Literal[
        "trial",
        "new",
        "reactivation",
        "upgrade",
        "downgrade",
        "interval",
        "renewal_off",
        "renewal_on",
        "churn",
    ]
    | None = None,
    source: Literal["plan", "add_on"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> PageEnvelope[SubscriptionChangeRow]:
    """Each change a Stripe event made to a plan's or an add-on's
    subscription, its MRR before and after (LEKA-554)."""
    found = await serve_page(
        session,
        changes_query(
            organisation_id=organisation_id,
            organisation=organisation,
            kind=kind,
            source=source,
            since=since,
            until=until,
        ),
        request=page,
        catalogue=CHANGE_SORTS,
        id_column=SubscriptionChange.id,
    )
    return PageEnvelope(data=await change_rows(session, found.items), next_cursor=found.next_cursor)


@router.get(
    "/billing/events",
    response_model=PageEnvelope[StripeEventRow],
    summary="Every Stripe event received",
)
async def list_stripe_events(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.BILLING_READ))],
    page: PageParams,
    event_type: Annotated[
        str | None, Query(alias="type", description="A Stripe type; * matches anything.")
    ] = None,
    outcome: Annotated[str | None, Query(description="applied, ignored or failed.")] = None,
    organisation_id: uuid.UUID | None = None,
    received_from: datetime | None = None,
    received_to: datetime | None = None,
    linked: Annotated[
        bool | None,
        Query(description="false: the events of a customer LEKA does not know (LEKA-554)."),
    ] = None,
) -> PageEnvelope[StripeEventRow]:
    """Each event Stripe sent, once: applied, ignored, or failed with its
    error and attempts until a delivery applies it (LEKA-554)."""
    found = await serve_page(
        session,
        stripe_events_query(
            type_=event_type,
            outcome=outcome,
            organisation_id=organisation_id,
            received_from=received_from,
            received_to=received_to,
            linked=linked,
        ),
        request=page,
        catalogue=STRIPE_SORTS,
        id_column=StripeEvent.id,
    )
    return PageEnvelope(
        data=await stripe_event_rows(session, found.items), next_cursor=found.next_cursor
    )


@router.get("/sources", response_model=PageEnvelope[SourceRow], summary="Every connected source")
async def list_sources(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.ENVIRONMENTS_READ))],
    page: PageParams,
    organisation_id: uuid.UUID | None = None,
    kind: str | None = None,
    source_status: Annotated[str | None, Query(alias="status")] = None,
    health: str | None = None,
    in_error: bool = False,
) -> PageEnvelope[SourceRow]:
    """Its credentials are never part of it: what a source is, how it stands."""
    found = await serve_page(
        session,
        sources_query(
            organisation_id=organisation_id,
            kind=kind,
            status=source_status,
            health=health,
            in_error=in_error,
        ),
        request=page,
        catalogue=SOURCE_SORTS,
        id_column=Source.id,
    )
    return PageEnvelope(data=await source_rows(session, found.items), next_cursor=found.next_cursor)


@router.get(
    "/environments/overview",
    response_model=EnvironmentsOverview,
    summary="Every organisation's environment, together",
)
async def get_environments_overview(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.ENVIRONMENTS_READ))],
) -> EnvironmentsOverview:
    """The sources across LEKA (connected, failing, degraded, not read for
    three hours), the services they found, the reads of the last 24 hours,
    and each connector LEKA CORE has with who uses it (LEKA-555).
    Demonstration organisations left out."""
    return await environments_overview(session, now=datetime.now(UTC))


@router.get(
    "/environments",
    response_model=PageEnvelope[EnvironmentRow],
    summary="Every organisation's environment",
)
async def list_environments(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.ENVIRONMENTS_READ))],
    page: PageParams,
    q: Annotated[
        str | None, Query(max_length=200, description="An organisation's name, slug or id.")
    ] = None,
    connected: Annotated[bool, Query(description="Only those with a source connected.")] = False,
    in_error: Annotated[bool, Query(description="Only those with a source failing.")] = False,
) -> PageEnvelope[EnvironmentRow]:
    """One row per organisation (LEKA-555): its state, its sources and those
    failing, its connectors, its last read, what was found, the reads that
    failed in the last 7 days."""
    found = await serve_page(
        session,
        environments_query(q=q, connected=connected, in_error=in_error),
        request=page,
        catalogue=ORGANISATION_SORTS,
        id_column=Workspace.id,
    )
    return PageEnvelope(
        data=await environment_rows(session, found.items, now=datetime.now(UTC)),
        next_cursor=found.next_cursor,
    )


@router.get(
    "/environments/{organisation_id}",
    response_model=EnvironmentDetail,
    summary="An organisation's environment",
)
async def get_environment(
    organisation_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.ENVIRONMENTS_READ))],
) -> EnvironmentDetail:
    """Its sources and their diagnostics, its latest reads, what they found,
    how sure LEKA is of what ties it together, the latest changes of that
    (LEKA-555). Never a credential nor a source's settings. A reading kept
    in the admin trail."""
    found = await environment_detail(session, organisation_id, now=datetime.now(UTC))
    if found is None:
        raise _not_found("organisation")
    _viewed(
        session, request, principal, "environment", organisation_id, workspace_id=organisation_id
    )
    return found


@router.get(
    "/environments/{organisation_id}/map",
    response_model=EnvironmentMap,
    summary="An organisation's map",
)
async def get_environment_map(
    organisation_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.ENVIRONMENTS_READ))],
    environment: Annotated[
        str | None, Query(max_length=100, description="Only what runs in it.")
    ] = None,
) -> EnvironmentMap:
    """What it runs and only the relationships its collected data supports,
    each confirmed (stated by a source, or accepted) or supposed (inferred),
    with the sources that state it and what says it, scanned for secrets;
    where it was read from, verified or not, and when (LEKA-555). A reading
    kept in the admin trail."""
    found = await environment_map(
        session, organisation_id, now=datetime.now(UTC), environment=environment
    )
    if found is None:
        raise _not_found("organisation")
    _viewed(
        session, request, principal, "environment", organisation_id, workspace_id=organisation_id
    )
    return found


@router.get(
    "/environments/{organisation_id}/syncs",
    response_model=PageEnvelope[SyncRunRow],
    summary="An organisation's reads of its sources",
)
async def list_environment_syncs(
    organisation_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.ENVIRONMENTS_READ))],
    page: PageParams,
    source_id: uuid.UUID | None = None,
    sync_status: Annotated[
        Literal["running", "succeeded", "failed", "abandoned"] | None,
        Query(alias="status", description="failed: those that failed or were abandoned."),
    ] = None,
) -> PageEnvelope[SyncRunRow]:
    """Each read of its sources, the latest first, with the diagnostic it
    ended on, cleaned of secrets (LEKA-555)."""
    found = await serve_page(
        session,
        sync_runs_query(organisation_id=organisation_id, source_id=source_id, status=sync_status),
        request=page,
        catalogue=SYNC_SORTS,
        id_column=SyncRun.id,
    )
    return PageEnvelope(
        data=await sync_run_rows(session, found.items), next_cursor=found.next_cursor
    )


# ── Incidents & notifications (LEKA-556) ─────────────────────────────────────


def _statuses(said: Sequence[str] | None) -> tuple[str, ...]:
    """`open` said as what it is: new and in progress."""
    found: list[str] = []
    for status_ in said or ():
        found += ["new", "in_progress"] if status_ == "open" else [status_]
    return tuple(dict.fromkeys(found))


@router.get("/incidents/summary", response_model=IncidentSummary, summary="Open incidents, counted")
async def get_incidents_summary(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.INCIDENTS_READ))],
) -> IncidentSummary:
    """The incidents new or in progress, by status, severity and category;
    those given to no one; those recurring."""
    return await incidents_summary(session)


@router.get(
    "/incidents/assignees",
    response_model=list[IncidentAssignee],
    summary="Who an incident may be given to",
)
async def list_incident_assignees(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.INCIDENTS_READ))],
) -> list[IncidentAssignee]:
    """LEKA's team, active: their name and address."""
    return await incident_assignees(session)


@router.get("/incidents", response_model=PageEnvelope[IncidentRow], summary="Every incident")
async def list_incidents(
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.INCIDENTS_READ))],
    page: PageParams,
    incident_status: Annotated[
        list[Literal["open", "new", "in_progress", "resolved", "closed"]] | None,
        Query(
            alias="status",
            description="One or several; `open`: new and in progress; every one when none.",
        ),
    ] = None,
    severity: Literal["critical", "high", "medium", "low"] | None = None,
    category: Literal[
        "intention_failed",
        "agent_failed",
        "api_error",
        "integration_disconnected",
        "sync_failed",
        "credits",
        "payment_failed",
        "platform",
    ]
    | None = None,
    recurring: Annotated[bool | None, Query(description="Three times in a day.")] = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Annotated[
        str | None, Query(max_length=200, description="An organisation's name or slug.")
    ] = None,
    mine: Annotated[bool, Query(description="Given to me.")] = False,
    unassigned: Annotated[bool, Query(description="Given to no one.")] = False,
    since: datetime | None = None,
    until: datetime | None = None,
    number: Annotated[int | None, Query(ge=1, description="INC-<number>.")] = None,
) -> PageEnvelope[IncidentRow]:
    """Each incident (LEKA-556), the last seen first by default: its
    organisation (none: the platform), category, severity, status,
    occurrences, recurring or not, who it is given to."""
    found = await serve_page(
        session,
        incidents_query(
            status=_statuses(incident_status),
            severity=severity,
            category=category,
            recurring=recurring,
            organisation_id=organisation_id,
            organisation=organisation,
            assignee_id=principal.admin_id if mine else None,
            unassigned=unassigned,
            since=since,
            until=until,
            number=number,
        ),
        request=page,
        catalogue=INCIDENT_SORTS,
        id_column=Incident.id,
    )
    return PageEnvelope(
        data=await incident_rows(session, found.items), next_cursor=found.next_cursor
    )


@router.get("/incidents/{incident_id}", response_model=IncidentRecord, summary="One incident")
async def get_incident(
    incident_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.INCIDENTS_READ))],
) -> IncidentRecord:
    """Its record and its history, the latest first: opened, each
    occurrence, recurring, given to someone, its status, the notes, resolved
    by LEKA when the problem went."""
    found = await incident_detail(session, incident_id)
    if found is None:
        raise _not_found("incident")
    return found


@router.patch(
    "/incidents/{incident_id}", response_model=IncidentRecord, summary="Deal with an incident"
)
async def update_incident(
    incident_id: uuid.UUID,
    payload: IncidentChange,
    request: Request,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.INCIDENTS_WRITE))],
) -> IncidentRecord:
    """Taken up, resolved, closed (for good) or taken up again; given to an
    active admin, or to no one (`assignee_id`: null); a note. Each kept in
    its history and in the admin trail."""
    try:
        incident = await change_incident(
            session,
            incident_id,
            payload,
            by_id=principal.admin_id,
            by_email=principal.email,
            now=datetime.now(UTC),
        )
    except IncidentError as error:
        if error.code == "not_found":
            raise _not_found("incident") from error
        raise ApiError(
            status.HTTP_409_CONFLICT
            if error.code == "reopened"
            else status.HTTP_422_UNPROCESSABLE_ENTITY,
            ErrorCode.CONFLICT if error.code == "reopened" else ErrorCode.VALIDATION_FAILED,
            str(error),
        ) from error
    audit_record(
        session,
        "admin.incident_updated",
        admin_id=principal.admin_id,
        admin_email=principal.email,
        target_type="incident",
        target_id=incident.id,
        workspace_id=incident.for_workspace_id,
        route=route_of(request),
        ip_prefix=principal.ip_prefix,
        detail={
            "number": incident.number,
            **payload.model_dump(mode="json", exclude_unset=True, exclude={"note"}),
            **({"note": True} if payload.note else {}),
        },
    )
    found = await incident_detail(session, incident.id)
    assert found is not None
    return found


@router.get(
    "/notifications",
    response_model=PageEnvelope[AdminNotificationRow],
    summary="The team's notifications",
)
async def list_notifications(
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.INCIDENTS_READ))],
    page: PageParams,
    unread: Annotated[bool, Query(description="Only those I have not read.")] = False,
    kind: Literal[
        "critical_incident",
        "payment_failed",
        "integration_disconnected",
        "repeated_errors",
        "capacity_near_limit",
        "abnormal_consumption",
    ]
    | None = None,
    organisation_id: uuid.UUID | None = None,
) -> PageEnvelope[AdminNotificationRow]:
    """What LEKA's team is told (LEKA-556), once each, the latest first,
    each said read or not by me, with its incident when it has one."""
    found = await serve_page(
        session,
        notifications_query(
            admin_id=principal.admin_id, unread=unread, kind=kind, organisation_id=organisation_id
        ),
        request=page,
        catalogue=NOTIFICATION_SORTS,
        id_column=AdminNotification.id,
    )
    return PageEnvelope(
        data=await notification_rows(session, found.items, admin_id=principal.admin_id),
        next_cursor=found.next_cursor,
    )


@router.get(
    "/notifications/unread", response_model=NotificationsCount, summary="My unread notifications"
)
async def count_unread_notifications(
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.INCIDENTS_READ))],
) -> NotificationsCount:
    return NotificationsCount(unread=await unread_count(session, principal.admin_id))


@router.post(
    "/notifications/read", response_model=NotificationsCount, summary="Mark notifications read"
)
async def read_notifications(
    payload: NotificationsRead,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.INCIDENTS_READ))],
) -> NotificationsCount:
    """Read by me: these, or every one not read yet. Each admin reads on
    their own; the history stays."""
    marked = await mark_read(
        session,
        principal.admin_id,
        ids=payload.ids,
        every=payload.every,
        now=datetime.now(UTC),
    )
    await session.flush()
    return NotificationsCount(unread=await unread_count(session, principal.admin_id), marked=marked)


@router.get(
    "/activity", response_model=PageEnvelope[ActivityRow], summary="What happened across LEKA"
)
async def list_activity(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.ACTIVITY_READ))],
    page: PageParams,
    kind: Annotated[
        str | None, Query(description="A kind; * matches anything, as `intention.*`.")
    ] = None,
    organisation_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    at_from: Annotated[datetime | None, Query(alias="from")] = None,
    at_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> PageEnvelope[ActivityRow]:
    found = await serve_page(
        session,
        activity_query(
            kind=kind,
            organisation_id=organisation_id,
            user_id=user_id,
            at_from=at_from,
            at_to=at_to,
        ),
        request=page,
        catalogue=ACTIVITY_SORTS,
        id_column=ActivityEvent.id,
    )
    return PageEnvelope(data=[activity_row(e) for e in found.items], next_cursor=found.next_cursor)


@router.get(
    "/audit", response_model=PageEnvelope[AdminAuditRow], summary="What LEKA's team did and read"
)
async def list_admin_audit(
    request: Request,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.AUDIT_READ))],
    page: PageParams,
    admin_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(description="An action; * matches anything.")] = None,
    organisation_id: uuid.UUID | None = None,
    outcome: str | None = None,
    at_from: Annotated[datetime | None, Query(alias="from")] = None,
    at_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> PageEnvelope[AdminAuditRow]:
    found = await serve_page(
        session,
        admin_audit_query(
            admin_id=admin_id,
            action=action,
            organisation_id=organisation_id,
            outcome=outcome,
            at_from=at_from,
            at_to=at_to,
        ),
        request=page,
        catalogue=AUDIT_SORTS,
        id_column=AdminAuditEvent.id,
    )
    # Most rows keep the admin's id only: the page says who by their address.
    emails = await admin_emails(
        session, {e.admin_id for e in found.items if e.admin_id and not e.admin_email}
    )
    # Who read the trail is in the trail (LEKA-546), with what they looked for.
    filters = {
        "admin_id": admin_id,
        "action": action,
        "organisation_id": organisation_id,
        "outcome": outcome,
        "from": at_from,
        "to": at_to,
    }
    audit_record(
        session,
        "admin.viewed_trail",
        admin_id=principal.admin_id,
        target_type="admin_audit_events",
        route=route_of(request),
        ip_prefix=principal.ip_prefix,
        detail={
            "filters": {k: str(v) for k, v in filters.items() if v is not None},
            "rows": len(found.items),
        },
    )
    return PageEnvelope(
        data=[
            AdminAuditRow(
                id=e.id,
                at=e.at,
                admin_id=e.admin_id,
                admin_email=e.admin_email or (emails.get(e.admin_id) if e.admin_id else None),
                action=e.action,
                outcome=e.outcome,
                target_type=e.target_type,
                target_id=e.target_id,
                organisation_id=e.for_workspace_id,
                route=e.route,
                request_id=e.request_id,
                session_id=e.session_id,
                ip_prefix=e.ip_prefix,
                detail=dict(e.detail),
            )
            for e in found.items
        ],
        next_cursor=found.next_cursor,
    )


# ── Sensitive operations ─────────────────────────────────────────────────────
#
# Each wants an Idempotency-Key header (8 to 100 characters, a UUID will do):
# the same request sent again answers what the first one did and does
# nothing; the same key with another request is a 409.

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=100,
        description="Unique per operation; send it again to retry safely.",
    ),
]


async def _once(
    request: Request,
    session: AsyncSession,
    principal: AdminPrincipal,
    key: str,
    body: BaseModel,
    run: Callable[[], Awaitable[OrganisationAction]],
) -> OrganisationAction:
    async def done() -> tuple[int, dict[str, object]]:
        try:
            result = await run()
        except ActionError as error:
            code = {404: ErrorCode.NOT_FOUND, 422: ErrorCode.VALIDATION_FAILED}.get(
                error.status_code, ErrorCode.CONFLICT
            )
            raise ApiError(error.status_code, code, error.message) from error
        return 200, result.model_dump(mode="json")

    try:
        _, answer, replayed = await once(
            session, principal, key, route_of(request), body.model_dump(mode="json"), done
        )
    except IdempotencyConflictError as error:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, str(error)) from error
    return OrganisationAction.model_validate({**answer, "replayed": replayed})


@router.post(
    "/organisations/{organisation_id}/suspend",
    response_model=OrganisationAction,
    summary="Suspend an organisation",
)
async def suspend_organisation(
    organisation_id: uuid.UUID,
    payload: ActionReason,
    request: Request,
    session: SessionDep,
    key: IdempotencyKey,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.ORGANISATIONS_WRITE))],
) -> OrganisationAction:
    """Writes refused, reads kept, the bill kept. Said in its own audit trail
    as done by LEKA; the reason stays in the admin trail."""
    return await _once(
        request,
        session,
        principal,
        key,
        payload,
        lambda: set_suspended(
            session,
            principal,
            organisation_id,
            suspended=True,
            reason=payload.reason,
            route=route_of(request),
        ),
    )


@router.post(
    "/organisations/{organisation_id}/reactivate",
    response_model=OrganisationAction,
    summary="Reactivate an organisation",
)
async def reactivate_organisation(
    organisation_id: uuid.UUID,
    payload: ActionReason,
    request: Request,
    session: SessionDep,
    key: IdempotencyKey,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.ORGANISATIONS_WRITE))],
) -> OrganisationAction:
    return await _once(
        request,
        session,
        principal,
        key,
        payload,
        lambda: set_suspended(
            session,
            principal,
            organisation_id,
            suspended=False,
            reason=payload.reason,
            route=route_of(request),
        ),
    )


@router.post(
    "/organisations/{organisation_id}/credits",
    response_model=OrganisationAction,
    summary="Add credits to an organisation's month",
)
async def add_organisation_credits(
    organisation_id: uuid.UUID,
    payload: CreditGrant,
    request: Request,
    session: SessionDep,
    key: IdempotencyKey,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.CREDITS_WRITE))],
) -> OrganisationAction:
    """A pack of this month's credits, said by whom and why: kept in its own
    audit trail and in the admin trail; gone when the month ends, as every
    pack."""
    return await _once(
        request,
        session,
        principal,
        key,
        payload,
        lambda: add_credits(
            session,
            principal,
            organisation_id,
            amount=payload.credits,
            reason=payload.reason,
            route=route_of(request),
        ),
    )


@router.post(
    "/organisations/{organisation_id}/credits/adjustments",
    response_model=OrganisationAction,
    summary="Give back or adjust an organisation's credits",
)
async def adjust_organisation_credits(
    organisation_id: uuid.UUID,
    payload: CreditAdjustment,
    request: Request,
    session: SessionDep,
    key: IdempotencyKey,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.CREDITS_WRITE))],
) -> OrganisationAction:
    """A line of its ledger (LEKA-553), written by LEKA's team: credits given
    back (`refund`, of a consumption it names) or adjusted (`adjustment`,
    added or taken), with the reason; counted in this month's allowance at
    once, written once for this Idempotency-Key, kept in its trail and in
    the admin trail."""
    return await _once(
        request,
        session,
        principal,
        key,
        payload,
        lambda: adjust_credits(
            session,
            principal,
            organisation_id,
            payload,
            key=key,
            route=route_of(request),
        ),
    )


@router.patch(
    "/organisations/{organisation_id}",
    response_model=OrganisationAction,
    summary="Change what LEKA keeps about an organisation",
)
async def update_organisation_info(
    organisation_id: uuid.UUID,
    payload: OrganisationUpdate,
    request: Request,
    session: SessionDep,
    key: IdempotencyKey,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.ORGANISATIONS_WRITE))],
) -> OrganisationAction:
    """Its name, country or size (LEKA-549), with a reason: what changed is
    said in its own audit trail as done by LEKA, the reason and the values
    before and after in the admin trail."""
    return await _once(
        request,
        session,
        principal,
        key,
        payload,
        lambda: update_organisation(
            session, principal, organisation_id, payload, route=route_of(request)
        ),
    )


@router.post(
    "/organisations/{organisation_id}/notes",
    response_model=NoteRow,
    status_code=status.HTTP_201_CREATED,
    summary="Write an internal note about an organisation",
)
async def add_organisation_note(
    organisation_id: uuid.UUID,
    payload: NoteCreate,
    request: Request,
    session: SessionDep,
    principal: Annotated[AdminPrincipal, Depends(require_admin(P.ORGANISATIONS_NOTES))],
) -> NoteRow:
    """For LEKA's team, never shown to the customer (LEKA-549). The admin
    trail says one was written, never what it says."""
    try:
        return await add_note(
            session, principal, payload, organisation_id=organisation_id, route=route_of(request)
        )
    except ActionError as error:
        raise _not_found("organisation") from error


# ── Passwords (LEKA-545) ─────────────────────────────────────────────────────
#
# A code by email rather than a link: the app is on a phone. Forgetting a
# password answers the same whether the address is an admin's or not.

FORGOT_PER_ACCOUNT = ratelimit.Limit(attempts=3, window_seconds=900)
CODE_PER_IP = ratelimit.Limit(attempts=20, window_seconds=60)


def get_admin_mailer(background: BackgroundTasks) -> EmailSender:
    """Emails leave after the response, so after the commit: a code is only
    sent once the database keeps it."""
    return DeferredEmailSender(build_email_sender(), background.add_task)


Mailer = Annotated[EmailSender, Depends(get_admin_mailer)]


async def _limit(*limits: tuple[str, str, ratelimit.Limit]) -> None:
    for scope, identifier, limit in limits:
        verdict = await ratelimit.consume(scope, identifier, limit)
        if not verdict.allowed:
            raise ApiError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                ErrorCode.RATE_LIMITED,
                "Too many attempts. Wait a little and try again.",
                headers={"Retry-After": str(verdict.retry_after_seconds)},
            )


@router.post(
    "/auth/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a code to choose a new password",
)
async def ask_password_reset(
    payload: AdminForgotPassword, request: Request, session: SessionDep, mailer: Mailer
) -> Response:
    """A code by email, valid 15 minutes, if the address is an active admin's.
    202 either way: nothing here says whether it is."""
    ip = client_ip(request)
    await _limit(
        ("admin-code:ip", ip or "unknown", CODE_PER_IP),
        ("admin-forgot:email", payload.email, FORGOT_PER_ACCOUNT),
    )
    sent = await forgot_password(session, payload.email, mailer)
    audit_record(
        session,
        "admin.password_reset_asked",
        admin_id=None,
        admin_email=payload.email,
        outcome="succeeded" if sent else "refused",
        route=route_of(request),
        ip_prefix=ip,
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/auth/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Choose a password with the code sent by email",
)
async def reset_password(
    payload: AdminResetPassword, request: Request, session: SessionDep
) -> Response:
    """For an invited admin's first password and for a forgotten one. Every
    session of the account ends; then sign in."""
    ip = client_ip(request)
    await _limit(("admin-code:ip", ip or "unknown", CODE_PER_IP))
    try:
        account = await redeem_code(session, payload.email, payload.code, payload.password)
    except CodeError as error:
        await audit_apart(
            "admin.code_refused",
            admin_id=None,
            admin_email=payload.email,
            route=route_of(request),
            ip_prefix=ip,
        )
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ErrorCode.TOKEN_INVALID,
            "This code is not valid, or no longer. Ask for a new one.",
        ) from error
    except PasswordRefusedError as error:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, ErrorCode.VALIDATION_FAILED, error.reason
        ) from error
    audit_record(
        session,
        "admin.password_set",
        admin_id=account.id,
        admin_email=account.email,
        target_type="admin",
        target_id=account.id,
        route=route_of(request),
        ip_prefix=ip,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/auth/change-password", response_model=AdminPasswordChanged, summary="Change my password"
)
async def change_my_password(
    payload: AdminChangePassword,
    request: Request,
    session: SessionDep,
    principal: AdminPrincipalDep,
) -> AdminPasswordChanged:
    """The current password, then the new one; the admin's other sessions end."""
    try:
        ended = await change_password(
            session, principal, payload.current_password, payload.password
        )
    except AdminAuthError as error:
        await audit_apart(
            "admin.password_change_refused",
            admin_id=principal.admin_id,
            admin_email=principal.email,
            route=route_of(request),
            ip_prefix=principal.ip_prefix,
        )
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INVALID_CREDENTIALS,
            "Your current password is not correct.",
        ) from error
    except PasswordRefusedError as error:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, ErrorCode.VALIDATION_FAILED, error.reason
        ) from error
    audit_record(
        session,
        "admin.password_changed",
        admin_id=principal.admin_id,
        target_type="admin",
        target_id=principal.admin_id,
        route=route_of(request),
        ip_prefix=principal.ip_prefix,
        detail={"sessions_ended": ended},
    )
    return AdminPasswordChanged(sessions_ended=ended)


# ── The team and its roles (LEKA-545) ────────────────────────────────────────

Manager = Annotated[AdminPrincipal, Depends(require_admin(P.ADMINS_MANAGE))]


def _team_error(error: team.TeamError) -> ApiError:
    code = ErrorCode.NOT_FOUND if error.status_code == 404 else ErrorCode.CONFLICT
    return ApiError(error.status_code, code, error.message)


@router.get("/admins", response_model=PageEnvelope[AdminRead], summary="LEKA's team")
async def list_admins(session: SessionDep, _: Manager) -> PageEnvelope[AdminRead]:
    """Every admin, invited, active or disabled, with their sessions open now."""
    return PageEnvelope(data=await team.members(session))


@router.post(
    "/admins",
    response_model=AdminRead,
    status_code=status.HTTP_201_CREATED,
    summary="Invite an admin",
)
async def invite_admin(
    payload: AdminInvite, request: Request, session: SessionDep, principal: Manager, mailer: Mailer
) -> AdminRead:
    """An account with a role, invited: an email carries the code to choose
    the password (72 hours)."""
    try:
        return await team.invite(
            session,
            principal,
            email=payload.email,
            name=payload.name,
            role=payload.role,
            sender=mailer,
            route=route_of(request),
        )
    except team.TeamError as error:
        raise _team_error(error) from error


@router.patch("/admins/{admin_id}", response_model=AdminRead, summary="Change an admin")
async def change_admin(
    admin_id: uuid.UUID,
    payload: AdminChange,
    request: Request,
    session: SessionDep,
    principal: Manager,
) -> AdminRead:
    """Name, role, active or disabled. Disabling ends every session at once.
    Never one's own role or access, never the last active Super Admin."""
    try:
        return await team.change(
            session,
            principal,
            admin_id,
            name=payload.name,
            role=payload.role,
            status=payload.status,
            route=route_of(request),
        )
    except team.TeamError as error:
        raise _team_error(error) from error


@router.post(
    "/admins/{admin_id}/invitation", response_model=AdminRead, summary="Send the invitation again"
)
async def resend_invitation(
    admin_id: uuid.UUID, request: Request, session: SessionDep, principal: Manager, mailer: Mailer
) -> AdminRead:
    try:
        return await team.resend(
            session, principal, admin_id, sender=mailer, route=route_of(request)
        )
    except team.TeamError as error:
        raise _team_error(error) from error


@router.post(
    "/admins/{admin_id}/sign-out",
    response_model=AdminSessionsEnded,
    summary="End an admin's sessions",
)
async def sign_admin_out(
    admin_id: uuid.UUID, request: Request, session: SessionDep, principal: Manager
) -> AdminSessionsEnded:
    try:
        ended = await team.sign_out_everywhere(
            session, principal, admin_id, route=route_of(request)
        )
    except team.TeamError as error:
        raise _team_error(error) from error
    return AdminSessionsEnded(sessions_ended=ended)


@router.get("/roles", response_model=AdminRolesRead, summary="What each role may do")
async def list_roles(session: SessionDep, _: AdminPrincipalDep) -> AdminRolesRead:
    """The four roles, what each grants now, and every permission with its
    module and kind of action (read, write, sensitive)."""
    return await team.roles(session)


@router.put(
    "/roles/{role}/permissions", response_model=AdminRoleRead, summary="Set what a role may do"
)
async def set_role_permissions(
    role: AdminRole,
    payload: AdminRolePermissionsUpdate,
    request: Request,
    session: SessionDep,
    principal: Manager,
) -> AdminRoleRead:
    """The whole list, replaced. Never the Super Admin's role; never what only
    a Super Admin may do. Takes effect at each admin's next request."""
    try:
        return await team.set_permissions(
            session, principal, role, payload.permissions, route=route_of(request)
        )
    except team.TeamError as error:
        raise _team_error(error) from error
