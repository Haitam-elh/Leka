"""The Admin API (LEKA-544): LEKA ADMIN's routes, under /api/v1/admin.

For LEKA's team, never for a customer. Every route but sign-in takes an
admin's bearer token and a permission of its role
(leka/admin/dependencies.py); a customer's session cookie opens none of
them. docs/admin/api.md is the contract, route by route.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status

from leka.admin import (
    AdminAuth,
    AdminAuthError,
    AdminMe,
    AdminPrincipalDep,
    AdminRole,
    AdminSignedIn,
    AdminSignIn,
    audit_apart,
    audit_record,
    client_ip,
    permissions_of,
    route_of,
)
from leka.api.errors import ApiError
from leka.core import ratelimit
from leka.core.config import settings
from leka.core.errors import ErrorCode
from leka.db import DatabaseSession

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
    )
    role = AdminRole(signed.account.role)
    return AdminSignedIn(
        token=signed.token,
        expires_at=signed.session.expires_at,
        idle_minutes=settings.admin_session_idle_minutes,
        admin=AdminMe(
            id=signed.account.id,
            email=signed.account.email,
            name=signed.account.name,
            role=role,
            permissions=sorted(permissions_of(role)),
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
