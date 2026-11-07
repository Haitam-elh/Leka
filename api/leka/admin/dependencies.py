"""Who may call the Admin API, checked on the server for every route (LEKA-544).

THE ONE PLACE A REQUEST SEES EVERY CUSTOMER. leka/db/repository.py says
`system_scope()` is never for serving a request, because a request has a
principal and a principal has one workspace. An admin is the deliberate
exception, and this is where it is made: the request runs in
`system_scope()` only after its bearer token has been resolved to an active
admin of LEKA's team — never from a customer's cookie, which this ignores.
docs/adr/016-leka-admin.md says why; tests/test_admin_access.py keeps it.

  get_admin         401 without a valid bearer token; the handler runs in
                    `system_scope()`, and the trail rows it writes name the
                    session (LEKA-546)
  require_admin(p)  403 unless the admin's role grants `p`; the refusal is
                    kept in the admin trail, apart from the rolled-back request
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from leka.admin import audit
from leka.admin.access import AdminPermission
from leka.admin.schemas import AdminPrincipal
from leka.admin.service import AdminAuth
from leka.db import DatabaseSession, system_scope
from leka.identity import truncate_ip

_bearer = HTTPBearer(
    auto_error=False, description="An admin session token (POST /admin/auth/sign-in)."
)


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    raw = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    return truncate_ip(raw)


def route_of(request: Request) -> str:
    return f"{request.method} {request.url.path}"


async def get_admin(
    request: Request,
    session: DatabaseSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AsyncIterator[AdminPrincipal]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to LEKA ADMIN.")
    principal = await AdminAuth(session).resolve(
        credentials.credentials, ip_prefix=client_ip(request)
    )
    if principal is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="This LEKA ADMIN session has ended. Sign in again.",
        )
    # Each row of the admin trail this request writes names its session.
    with system_scope(), audit.acting_in(principal.session_id):
        yield principal


AdminPrincipalDep = Annotated[AdminPrincipal, Depends(get_admin, scope="function")]


def require_admin(
    permission: AdminPermission, *also: AdminPermission
) -> Callable[..., Coroutine[Any, Any, AdminPrincipal]]:
    """The route needs `permission`, and each of `also` (an export: the list's
    reading and the export's own, LEKA-557). Refused by default: what a role
    does not grant (leka/admin/access.py) is refused here, not hidden on a
    screen; the first permission missing is the one said."""

    async def dependency(request: Request, principal: AdminPrincipalDep) -> AdminPrincipal:
        missing = [p for p in (permission, *also) if p not in principal.permissions]
        if missing:
            await audit.apart(
                "admin.refused",
                admin_id=principal.admin_id,
                admin_email=principal.email,
                route=route_of(request),
                ip_prefix=principal.ip_prefix,
                detail={"permission": missing[0].value, "role": principal.role.value},
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Your role ({principal.role.value}) does not allow {missing[0].value}.",
            )
        return principal

    return dependency
