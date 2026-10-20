"""Three exception handlers, so a client meets one error shape.

FastAPI produces three kinds of failure that look nothing like each other:

    HTTPException           whatever shape the author chose
    RequestValidationError  Pydantic's, {"detail": [{"loc": [...], ...}]}
    an unhandled exception  a bare 500 from Starlette

Until all three pass through a handler registered on the application, a
client has to know three formats — and the one everybody forgets is the
second, which is also the most common. A missing field answers in a
different shape from a business rule saying no.

That was not theory here. web/lib/api.ts carried a function whose only job
was to unpick Pydantic's 422, plus a separate branch for `detail` being a
string, plus a third for it being an object. That code existed because this
file did not.

The SHAPE itself lives in leka.core.errors, low enough that the CSRF
middleware in leka.identity can use it too — it builds its own response and
never reaches a handler. This module is the framework wiring.

NOTHING INTERNAL EVER REACHES THE CLIENT. A 500 says that something failed
and gives the request id; the traceback, the SQL and the table names go to
the log. That holds in every environment, not only production — a rule with
an exception is a rule somebody will misconfigure, and a mislabelled staging
environment is all it would take.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

from leka.core.config import settings
from leka.core.errors import (
    INTERNAL_ERROR_MESSAGE,
    ErrorCode,
    ErrorEnvelope,
    FieldError,
    error_envelope,
)

logger = structlog.get_logger(__name__)


def _request_id_of(request: Request) -> str | None:
    """The id stamped on this request, even after the context has unwound.

    request.state is what survives an exception propagating out through the
    middleware that set the context variable.
    """
    return getattr(request.state, "request_id", None)


# What an HTTPException means when it arrives without a code of its own —
# a 404 from the router, a refusal raised by code written before this file.
DEFAULT_CODE_FOR_STATUS: dict[int, ErrorCode] = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.VALIDATION_FAILED,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.NOT_AUTHENTICATED,
    status.HTTP_403_FORBIDDEN: ErrorCode.PERMISSION_DENIED,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    status.HTTP_422_UNPROCESSABLE_CONTENT: ErrorCode.VALIDATION_FAILED,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
    status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.SERVICE_UNAVAILABLE,
}


class ApiError(HTTPException):
    """Raise this rather than HTTPException.

    Carries the code and the field details through to the handler, so a
    route never builds a response body by hand. It is still an
    HTTPException, so anything already catching one keeps working.
    """

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        *,
        details: list[FieldError] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.details = details


def _code_and_message(error: StarletteHTTPException) -> tuple[ErrorCode, str]:
    """Read a code and a sentence out of whatever was raised.

    Three shapes arrive here and all three are legitimate:

      ApiError                    carries its own code
      HTTPException(detail=dict)  LEKA-330's {"detail": ..., "code": ...}
      HTTPException(detail=str)   governance, and FastAPI's own 404

    The last two are met where they are rather than migrated away from.
    Rewriting every call site would be a large diff whose only effect is to
    make this function shorter.
    """
    if isinstance(error, ApiError):
        return error.code, str(error.detail)

    fallback = DEFAULT_CODE_FOR_STATUS.get(error.status_code, ErrorCode.INTERNAL_ERROR)

    # Typed as `object`, and that is not decoration: Starlette declares
    # `detail` as str, while LEKA-330 has been putting a dict there since it
    # shipped. mypy is right about the annotation and wrong about the
    # runtime, so the annotation is widened where we actually look.
    detail: object = error.detail
    if isinstance(detail, dict):
        raw = detail.get("code")
        message = str(detail.get("detail", "")) or fallback.value
        try:
            return ErrorCode(str(raw)), message
        except ValueError:
            return fallback, message

    return fallback, str(detail) if detail else fallback.value


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Everything raised deliberately: ours, FastAPI's, Starlette's 404."""
    error = exc if isinstance(exc, StarletteHTTPException) else StarletteHTTPException(500)
    code, message = _code_and_message(error)

    return JSONResponse(
        status_code=error.status_code,
        content=error_envelope(
            code,
            message,
            details=getattr(error, "details", None),
            request_id=_request_id_of(request),
        ),
        # Preserved on purpose: Retry-After on a 429, WWW-Authenticate on a
        # 401. Dropping them would make the body advisory and the protocol
        # silent.
        headers=getattr(error, "headers", None),
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Pydantic's 422, in our shape.

    The one that matters most: it is the error a client meets most often and
    the one FastAPI answers in a shape nothing else uses, which is how a
    frontend ends up writing a parser for it.
    """
    details: list[FieldError] = []
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    for item in errors:
        # loc is ("body", "email") or ("query", "limit"): the first element
        # says where, the rest is the path a client would recognise.
        location = [str(part) for part in item.get("loc", ())][1:]
        details.append(
            FieldError(
                field=".".join(location) or "body",
                message=str(item.get("msg", "invalid value")),
            )
        )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_envelope(
            ErrorCode.VALIDATION_FAILED,
            "The request is not valid.",
            details=details or None,
            request_id=_request_id_of(request),
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """A bug. Logged in full, answered with nothing.

    The traceback, the SQL, the table names and the exception type all go to
    the log, where the request id ties them to this response. The client
    gets a sentence and that id.

    The same in every environment. Making it chattier in development would
    mean the safe path is the one nobody ever exercises.
    """
    logger.exception(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        exception_type=type(exc).__name__,
    )
    request_id = _request_id_of(request)
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_envelope(
            ErrorCode.INTERNAL_ERROR,
            INTERNAL_ERROR_MESSAGE,
            request_id=request_id,
        ),
    )
    _readable_by_the_page(request, response, request_id)
    return response


def _readable_by_the_page(request: Request, response: JSONResponse, request_id: str | None) -> None:
    """The headers CORS and the request id would have put on it. Starlette
    answers an unhandled exception from its outermost middleware, outside
    both: without them the browser hides the 500 from the page, which then
    says « check your connection » for every bug (2026-10-20). The same
    origins as CORSMiddleware's, never another."""
    # Here, not at the top: request_id.py reaches identity, which reaches
    # what answers its errors through this module.
    from leka.api.request_id import REQUEST_ID_HEADER

    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    origin = request.headers.get("origin")
    if origin and origin in settings.cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = REQUEST_ID_HEADER
        response.headers.add_vary_header("Origin")


def register_error_handlers(app: FastAPI) -> None:
    """Wire all three onto the application.

    On the app rather than on a router: a 404 for a path matching no route
    never reaches a router at all, and that is the response a client is most
    likely to meet first.
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


# Declared once and attached to every route, so api-types.ts types the error
# shape that is actually returned rather than FastAPI's default.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorEnvelope, "description": description}
    for code, description in (
        (400, "The request could not be understood."),
        (401, "Not signed in, or the session has expired."),
        (403, "Signed in, but not allowed to do this."),
        (404, "No such thing, or not yours to see."),
        (409, "The request conflicts with the current state."),
        (422, "The request is well formed but not valid."),
        (429, "Too many requests."),
        (500, "Something went wrong on our side."),
    )
}


__all__ = [
    "DEFAULT_CODE_FOR_STATUS",
    "ERROR_RESPONSES",
    "ApiError",
    "register_error_handlers",
]
