"""A rate limit on every route, without every route remembering to ask.

Before this, leka/api/identity.py called `_enforce` by hand at seven call
sites and nothing else was limited at all. A route that forgot the call was
simply unlimited, and nothing said so — the failure mode of any control that
depends on being invoked.

A middleware instead, for the reason csrf.py gives: a route added next year
is covered without its author knowing this file exists.

WHAT IT DOES NOT REPLACE. The authentication routes keep their own, much
stricter limits — five sign-ins a minute per address, three registrations an
hour. Those are tuned to specific attacks and this is a backstop, not a
substitute. A request passes through both.

THE KEY IS THE CALLER, NOT THE WORKSPACE, and that is a deliberate
departure. Keying by workspace would mean resolving the session to a
membership on every single request — a database read before we are willing
to say whether we will even serve the request, including for the requests we
are about to refuse. A limiter that costs a query per refusal is a way to
amplify an attack rather than absorb it. So the key is the session when
there is one and the client address otherwise, which bounds one caller
without asking the database anything.

The consequence is honest and worth knowing: two people in the same
workspace get a bucket each. If per-tenant quota becomes a billing concern
rather than an abuse concern, it belongs in a different mechanism anyway,
counted after the work is done rather than before it.

FAILS OPEN. leka.core.ratelimit already does, loudly. A Redis hiccup must
not lock every customer out of the product.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from leka.core import ratelimit
from leka.core.config import settings
from leka.core.errors import ErrorCode, error_envelope

# The backstop. Generous on purpose: anything that trips this is either a
# runaway client or an attack, and legitimate use of the product does not
# come close. The specific limits that matter live in leka.core.ratelimit.
DEFAULT_LIMIT = ratelimit.Limit(attempts=300, window_seconds=60)

# The IETF draft spelling (draft-ietf-httpapi-ratelimit-headers). Sent on
# EVERY response, not only on a refusal: a client that can see it coming can
# slow down, and one that only learns at 429 has already been refused.
LIMIT_HEADER = "RateLimit-Limit"
REMAINING_HEADER = "RateLimit-Remaining"
RESET_HEADER = "RateLimit-Reset"
RETRY_AFTER_HEADER = "Retry-After"

# Never limited.
#
# /health is polled by whatever watches the service. Refusing it would make
# a busy probe look like an outage, which is the one failure this must not
# invent. CORS preflights carry no credentials and do no work.
EXEMPT_PATHS = frozenset({f"{settings.api_v1_prefix}/health"})
EXEMPT_METHODS = frozenset({"OPTIONS"})


def caller_key(request: Request) -> str:
    """Who to count against: the session if there is one, the address if not.

    The session cookie is HASHED before it becomes a Redis key. It is a
    credential — the whole of LEKA-330 rests on it being unguessable — and a
    key in Redis is something an operator reads over someone's shoulder, a
    `KEYS *` dumps, and a monitoring tool exports.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        return "s:" + hashlib.sha256(token.encode()).hexdigest()[:32]

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return "i:" + forwarded.split(",")[0].strip()
    return "i:" + (request.client.host if request.client else "unknown")


def _apply_headers(response: Response, verdict: ratelimit.LimitVerdict) -> None:
    response.headers[LIMIT_HEADER] = str(DEFAULT_LIMIT.attempts)
    response.headers[REMAINING_HEADER] = str(verdict.remaining)
    response.headers[RESET_HEADER] = str(verdict.retry_after_seconds)


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Count the request, refuse it if there have been too many."""
    if request.method in EXEMPT_METHODS or request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    verdict = await ratelimit.consume("api", caller_key(request), DEFAULT_LIMIT)

    if not verdict.allowed:
        refusal = JSONResponse(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            content=error_envelope(
                ErrorCode.RATE_LIMITED,
                "Too many requests. Wait a moment and try again.",
            ),
        )
        refusal.headers[RETRY_AFTER_HEADER] = str(verdict.retry_after_seconds)
        _apply_headers(refusal, verdict)
        return refusal

    response = await call_next(request)
    _apply_headers(response, verdict)
    return response


__all__ = [
    "DEFAULT_LIMIT",
    "LIMIT_HEADER",
    "REMAINING_HEADER",
    "RESET_HEADER",
    "caller_key",
    "rate_limit_middleware",
]
