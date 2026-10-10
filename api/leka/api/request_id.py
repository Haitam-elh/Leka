"""One identifier per request, from the first byte to the last log line.

The cheapest diagnostic tool there is for someone working alone. "Give me
the request id" replaces an hour of archaeology: the client has it in a
response header and in every error body, and every log line the request
produced carries the same value.

A middleware rather than a dependency, for the reason csrf.py gives: a route
added next year is covered without its author knowing this file exists. And
a middleware also covers what a dependency cannot — a request refused by
CSRF, a body that never parsed, a path matching no route at all.

The context variable and the generator live in leka.core.request_context, so
that code below leka.api can read the current id. This is the HTTP half.

structlog needs nothing new: leka.core.logging already runs
`merge_contextvars`, so binding here puts the id on every line
automatically, including lines written by code that has never heard of this
module.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response

from leka.api.identity import client_ip
from leka.core.request_context import (
    current_request_id,
    new_request_id,
    reset_request_id,
    reset_request_origin,
    set_request_id,
    set_request_origin,
)

REQUEST_ID_HEADER = "X-Request-ID"

# What we accept from a proxy. Deliberately narrow: the value ends up in log
# lines and in a response header, so anything unchecked would be a way to
# write whatever somebody likes into both.
_ACCEPTABLE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Stamp the request, bind it for logging, return it in the response.

    X-Request-ID is honoured when it arrives and passes the check above. A
    proxy or a load balancer in front of us has usually already stamped one,
    and two identifiers for the same request is worse than none.
    """
    incoming = request.headers.get(REQUEST_ID_HEADER)
    request_id = incoming if incoming and _ACCEPTABLE.match(incoming) else new_request_id()

    # On the request as well as in the context variable, and that is not
    # belt and braces. An unhandled exception propagates OUT through this
    # middleware — running the `finally` below — before Starlette's
    # outermost handler builds the 500. By then the context variable is
    # already reset, so the one response where the id matters most would
    # have gone out without one. request.state survives the unwinding.
    request.state.request_id = request_id
    token = set_request_id(request_id)
    # Where it came from, for the audit trail (LEKA-407).
    # The address as rate limiting reads it (identity.client_ip): one reading.
    origin = set_request_origin(client_ip(request), request.headers.get("user-agent"))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
        reset_request_id(token)
        reset_request_origin(origin)

    # Set after the handler, so a route writing its own headers cannot drop
    # it by accident.
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


__all__ = [
    "REQUEST_ID_HEADER",
    "current_request_id",
    "new_request_id",
    "request_id_middleware",
]
