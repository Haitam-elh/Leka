"""The Admin API (LEKA-544): LEKA ADMIN's routes, under /api/v1/admin.

For LEKA's team, never for a customer. Every route but sign-in takes an
admin's bearer token and a permission of its role
(leka/admin/dependencies.py); a customer's session cookie opens none of
them. docs/admin/api.md is the contract, route by route.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, Response, status
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
    AdminInvite,
    AdminMe,
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
    AgentStat,
    CodeError,
    CreditGrant,
    CreditsBreakdown,
    IdempotencyConflictError,
    OrganisationAction,
    OrganisationCredits,
    OrganisationDetail,
    OrganisationMembers,
    OrganisationRef,
    OrganisationRow,
    PasswordRefusedError,
    Period,
    RenewalError,
    SourceRow,
    StripeEventRow,
    SubscriptionRow,
    UserDetail,
    UserRow,
    activity_query,
    activity_row,
    add_credits,
    admin_audit_query,
    admin_emails,
    agent_stats,
    audit_apart,
    audit_record,
    change_password,
    client_ip,
    credits_breakdown,
    credits_of,
    forgot_password,
    intention_detail,
    intention_rows,
    intentions_query,
    once,
    organisation_detail,
    organisation_members,
    organisation_rows,
    organisations_query,
    overview,
    permissions_now,
    redeem_code,
    require_admin,
    route_of,
    set_suspended,
    source_rows,
    sources_query,
    stripe_event_rows,
    stripe_events_query,
    subscription_rows,
    subscriptions_query,
    team,
    user_detail,
    user_rows,
    users_query,
    window_of,
)
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.billing import BillingAccount, StripeEvent
from leka.connectors import Source
from leka.core import ratelimit
from leka.core.config import settings
from leka.core.errors import ErrorCode
from leka.db import DatabaseSession, SortableField
from leka.identity import DeferredEmailSender, EmailSender, User, build_email_sender
from leka.intentions import Intention
from leka.platform import Workspace

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
SUBSCRIPTION_SORTS = _sorts(
    ("updated_at", BillingAccount.updated_at, "one row per organisation"),
    ("created_at", BillingAccount.created_at, "one row per organisation"),
    default="updated_at",
)
STRIPE_SORTS = _sorts(
    ("received_at", StripeEvent.received_at, "one row per Stripe event"), default="received_at"
)
SOURCE_SORTS = _sorts(
    ("created_at", Source.created_at, "a few per organisation"),
    ("name", Source.name, "a few per organisation"),
    default="created_at",
)
AUDIT_SORTS = _sorts(("at", AdminAuditEvent.at, "ix_admin_audit_events_at"), default="at")
ACTIVITY_SORTS = _sorts(("at", ActivityEvent.at, "ix_activity_events_kind_at"), default="at")

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


@router.get("/users", response_model=PageEnvelope[UserRow], summary="Every person")
async def list_users(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.USERS_READ))],
    page: PageParams,
    q: Annotated[str | None, Query(max_length=200, description="Email, name or id.")] = None,
    organisation_id: uuid.UUID | None = None,
    verified: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> PageEnvelope[UserRow]:
    found = await serve_page(
        session,
        users_query(
            q=q,
            organisation_id=organisation_id,
            verified=verified,
            created_from=created_from,
            created_to=created_to,
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
    "/intentions", response_model=PageEnvelope[AdminIntentionRow], summary="Every intention"
)
async def list_intentions(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.INTENTIONS_READ))],
    page: PageParams,
    organisation_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    intention_status: Annotated[
        str | None,
        Query(
            alias="status",
            description="pending, running, completed, failed, cancelled, or LEKA's own",
        ),
    ] = None,
    kind: str | None = None,
    agent: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> PageEnvelope[AdminIntentionRow]:
    found = await serve_page(
        session,
        intentions_query(
            organisation_id=organisation_id,
            user_id=user_id,
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
    return PageEnvelope(
        data=await intention_rows(session, found.items), next_cursor=found.next_cursor
    )


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
    """Its timeline, its runs and their errors, what it cost. What the
    customer wrote and what agents delivered (`content`) only for a role with
    intentions:content, each reading kept in the admin trail."""
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


@router.get(
    "/agents", response_model=PageEnvelope[AgentStat], summary="Every agent's use and performance"
)
async def list_agents(
    session: SessionDep,
    _: Annotated[AdminPrincipal, Depends(require_admin(P.AGENTS_READ))],
    since: datetime | None = None,
    until: datetime | None = None,
    organisation_id: uuid.UUID | None = None,
    agent: str | None = None,
    model: str | None = None,
) -> PageEnvelope[AgentStat]:
    """One row per agent that ran, the most used first; one page."""
    return PageEnvelope(
        data=await agent_stats(
            session,
            since=since,
            until=until,
            organisation_id=organisation_id,
            agent=agent,
            model=model,
        )
    )


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
) -> PageEnvelope[SubscriptionRow]:
    found = await serve_page(
        session,
        subscriptions_query(plan=plan, status=subscription_status, interval=interval),
        request=page,
        catalogue=SUBSCRIPTION_SORTS,
        id_column=BillingAccount.id,
    )
    return PageEnvelope(
        data=await subscription_rows(session, found.items), next_cursor=found.next_cursor
    )


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
) -> PageEnvelope[StripeEventRow]:
    found = await serve_page(
        session,
        stripe_events_query(
            type_=event_type,
            outcome=outcome,
            organisation_id=organisation_id,
            received_from=received_from,
            received_to=received_to,
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
            code = ErrorCode.NOT_FOUND if error.status_code == 404 else ErrorCode.CONFLICT
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
