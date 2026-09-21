"""Double-submit CSRF protection.

SameSite=Lax already stops a cross-site form from carrying our session
cookie, and every mutation we serve is POST, PATCH or DELETE. This is the
second layer: it is what remains if the cookie ever has to become
SameSite=None because the frontend and the API stop sharing a parent domain.
See docs/adr/009-cookie-strategy.md.

The check runs as middleware rather than as a dependency on each route, so a
route added later is covered without its author knowing this file exists.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.status import HTTP_403_FORBIDDEN

from leka.core.config import settings
from leka.core.errors import ErrorCode, error_envelope
from leka.identity.cookies import CSRF_COOKIE_NAME, CSRF_HEADER_NAME

logger = structlog.get_logger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Routes reached before a session exists. Requiring a CSRF token here would
# mean requiring one from someone who has never been issued one.
EXEMPT_PATHS = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/verify",
    "/api/v1/auth/password/forgot",
    "/api/v1/auth/password/reset",
)


async def csrf_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Refuse a state-changing request whose CSRF token does not match.

    Only enforced when a session cookie is present: a request with no session
    has nothing to hijack, and demanding a token from it would break the
    sign-in flow itself.
    """
    if request.method in SAFE_METHODS:
        return await call_next(request)
    if any(request.url.path.startswith(path) for path in EXEMPT_PATHS):
        return await call_next(request)
    if settings.session_cookie_name not in request.cookies:
        return await call_next(request)

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)

    if not cookie_token or not header_token:
        return _refuse("missing", request)
    if not hmac.compare_digest(cookie_token, header_token):
        return _refuse("mismatch", request)

    return await call_next(request)


def _refuse(reason: str, request: Request) -> JSONResponse:
    """Refuse, in the one error shape the API returns.

    Built here rather than raised, because middleware runs outside the chain
    that turns exceptions into responses — nothing this function raises
    would ever reach leka.api.errors. So it assembles the envelope itself,
    from leka.core.errors, which is low enough in the dependency order for
    this module to import.

    Before LEKA-333 this returned {"detail": ..., "code": ...} and was a
    fourth error shape nobody had counted.
    """
    logger.info("csrf_refused", reason=reason, path=request.url.path)
    return JSONResponse(
        status_code=HTTP_403_FORBIDDEN,
        content=error_envelope(
            ErrorCode.CSRF_FAILED,
            "This request is missing its CSRF token. Reload the page and try again.",
        ),
    )
