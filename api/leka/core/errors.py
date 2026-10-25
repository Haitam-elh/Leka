"""The error contract: one shape, one set of codes, for the whole API.

    {
      "error": {
        "code": "validation_failed",
        "message": "The request is not valid.",
        "details": [{"field": "email", "message": "not a valid email"}],
        "request_id": "01JBRQ7X4K9MZ8W2N5V3TYFHDC"
      }
    }

Wrapped in `error` rather than flat, because a single resource is returned
unwrapped: a flat body would collide the day a resource has a field called
`code`. The wrapper makes the discriminator structural instead of "look at
the status and guess".

WHY THIS IS IN leka.core AND NOT leka.api. The FastAPI exception handlers
live in leka.api.errors, where they belong. But the CSRF middleware builds
its own response and never reaches a handler — middleware runs outside the
chain that converts exceptions — and it lives in leka.identity, which sits
below leka.api and may not import from it. Left alone it would have gone on
returning a fourth shape, which is precisely what this contract exists to
end. So the SHAPE lives here, where every layer can reach it, and the
FRAMEWORK WIRING lives up top.

THE CODES ARE A PUBLIC API. Somebody will write `if (code === "...")`.
Adding a value is a compatible change; renaming or removing one is not. See
docs/api.md.
"""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field

from leka.core.request_context import current_request_id


class ErrorCode(enum.StrEnum):
    """Every machine-readable code the API can return.

    The authentication codes carry the spelling LEKA-330 shipped. They were
    moved here rather than renamed, because the frontend already switches on
    them and a rename would be a breaking change for nothing.
    """

    # ── Platform ─────────────────────────────────────────────────────────
    VALIDATION_FAILED = "validation_failed"
    NOT_AUTHENTICATED = "not_authenticated"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"

    # ── Request patterns ─────────────────────────────────────────────────
    INVALID_CURSOR = "invalid_cursor"
    INVALID_SORT = "invalid_sort"
    INVALID_FILTER = "invalid_filter"
    # A client asked for a version of a contract the API does not serve
    # (LEKA-376: Leka-Context-Contract).
    CONTRACT_UNSUPPORTED = "contract_unsupported"

    # ── Intentions ───────────────────────────────────────────────────────
    # Nothing about the company's technology (2026-10-14).
    OFF_TOPIC = "off_topic"
    # Its agents not launched (2026-10-14): which, and why, in the message;
    # the code says what to do about it.
    AGENT_UNAVAILABLE = "agent_unavailable"
    AGENT_INPUTS_MISSING = "agent_inputs_missing"
    AGENT_NOT_PROPOSED = "agent_not_proposed"
    CREDITS_SHORT = "credits_short"
    # What it pays for (2026-10-14): Free runs no agent; others, those
    # bought. The screens offer the plan, or the agent and its bundles.
    PLAN_REQUIRED = "plan_required"
    AGENT_NOT_OWNED = "agent_not_owned"
    # An Enterprise organisation asks once a source is connected (2026-10-25):
    # the screens lock the question and say « Connectez Confluence ».
    SOURCE_REQUIRED = "source_required"

    # ── Authentication (LEKA-330, spelling preserved) ────────────────────
    INVALID_CREDENTIALS = "invalid_credentials"
    ACCOUNT_UNVERIFIED = "account_unverified"
    TOKEN_INVALID = "token_invalid"  # noqa: S105
    TOKEN_EXPIRED = "token_expired"  # noqa: S105
    PASSWORD_TOO_SHORT = "password_too_short"  # noqa: S105
    PASSWORD_BREACHED = "password_breached"  # noqa: S105
    SESSION_EXPIRED = "session_expired"
    # Closing an account that is the last owner of a workspace others use.
    LAST_OWNER = "last_owner"
    CSRF_FAILED = "csrf_failed"

    # ── Billing ──────────────────────────────────────────────────────────
    # One user or source more than the plan allows (LEKA-463): a higher plan
    # is named in the message.
    PLAN_LIMIT = "plan_limit"


# What a 500 says out loud. Fixed, and deliberately uninformative: whoever
# reads it has the request id, and everything else is in our logs.
INTERNAL_ERROR_MESSAGE = "Something went wrong on our side. Quote the request id if you contact us."


class FieldError(BaseModel):
    """One thing wrong with one field."""

    field: str = Field(description="Dotted path to the field, as the client sent it.")
    message: str = Field(description="What is wrong with it, in a sentence.")


class ErrorBody(BaseModel):
    """The contents of an error response."""

    code: ErrorCode = Field(description="Stable machine-readable code. Branch on this.")
    message: str = Field(description="One sentence, safe to show a person.")
    details: list[FieldError] | None = Field(
        default=None,
        description="Per-field problems, present only when the request body was at fault.",
    )
    request_id: str | None = Field(
        default=None,
        description="Matches the X-Request-ID response header and our log lines.",
    )


class ErrorEnvelope(BaseModel):
    """Every error response the API returns, whatever the status."""

    error: ErrorBody


def error_envelope(
    code: ErrorCode,
    message: str,
    *,
    details: list[FieldError] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the body of an error response, request id included.

    The one place that shape is assembled. A caller anywhere in the stack
    gets the same result, which is the whole point of putting it here.

    `request_id` overrides the context variable, for the one caller that
    needs it: the handler for unhandled exceptions runs after the request
    has already unwound past the middleware that set it.
    """
    body = ErrorBody(
        code=code,
        message=message,
        details=details,
        request_id=request_id or current_request_id(),
    )
    return ErrorEnvelope(error=body).model_dump(mode="json", exclude_none=True)


__all__ = [
    "INTERNAL_ERROR_MESSAGE",
    "ErrorBody",
    "ErrorCode",
    "ErrorEnvelope",
    "FieldError",
    "error_envelope",
]
