"""What systems send LEKA: the deliveries of webhook sources (LEKA-350).

    POST /webhooks/sources/{id}    a delivery — no session: signed

NO SESSION, NO CSRF, NO PERMISSION: the sender is a system, not a person.
What authenticates it is its signature, which leka/ingestion/webhooks.py
checks against the source's secret before anything is written. The
workspace is the source's, found from the id in the path — the address the
admin gave the system; the signature is what proves the sender may use it.

A route validates, calls one service, and returns (architecture rule 6).
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from leka.api.errors import ApiError
from leka.core.errors import ErrorCode
from leka.ingestion.webhooks import MAX_BODY_BYTES, DeliveryRefusedError, Refused, receive

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ANSWERS: dict[Refused, tuple[int, ErrorCode]] = {
    "unknown": (status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND),
    "signature": (status.HTTP_401_UNAUTHORIZED, ErrorCode.NOT_AUTHENTICATED),
    "stale": (status.HTTP_401_UNAUTHORIZED, ErrorCode.NOT_AUTHENTICATED),
    "inactive": (status.HTTP_409_CONFLICT, ErrorCode.CONFLICT),
    "busy": (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.RATE_LIMITED),
    "malformed": (status.HTTP_400_BAD_REQUEST, ErrorCode.VALIDATION_FAILED),
    "unmapped": (status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED),
    "too_large": (status.HTTP_413_CONTENT_TOO_LARGE, ErrorCode.VALIDATION_FAILED),
}


class DeliveryAccepted(BaseModel):
    """A delivery kept — not yet stored: the source's next pass stores it."""

    delivery: uuid.UUID = Field(description="LEKA's id for it, as its log shows it.")
    status: Literal["pending", "ignored"] = Field(
        description="pending: to be stored; ignored: none of the definition's resources is it."
    )
    resource: str | None
    records: int = Field(description="Records it holds, to store.")
    gone: int = Field(description="Records it says were deleted.")


@router.post(
    "/sources/{source_id}",
    response_model=DeliveryAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def deliver(source_id: uuid.UUID, request: Request) -> DeliveryAccepted:
    """A delivery to a webhook source, signed with its secret."""
    body = await _bounded(request)
    headers = {name.lower(): value for name, value in request.headers.items()}
    try:
        accepted = await receive(source_id, headers, body)
    except DeliveryRefusedError as refused:
        raise _refusal(refused.reason, refused.message, refused.retry_after) from None
    return DeliveryAccepted(
        delivery=accepted.delivery,
        status=accepted.status,
        resource=accepted.resource,
        records=accepted.records,
        gone=accepted.gone,
    )


async def _bounded(request: Request) -> bytes:
    """The body, read no further than the limit: a sender that says, or
    sends, more is refused before it is all in memory."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise _too_large()
    return bytes(body)


def _too_large() -> ApiError:
    return _refusal("too_large", f"A delivery is {MAX_BODY_BYTES} bytes at most.", None)


def _refusal(reason: Refused, message: str, retry_after: int | None) -> ApiError:
    code, error = ANSWERS[reason]
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return ApiError(code, error, message, headers=headers)
