"""Receiving what a webhook source is sent (LEKA-350).

    POST /api/v1/webhooks/sources/{id}   ──▶  receive()
        a webhook source by that id              else 404, whoever asks
        signed with its secret                   else 401 — nothing written
        switched on                              else 409
        within its rate and its backlog          else 429 — the sender retries
        what the definition says it holds        else 400 / 422 — logged
        kept, pending, with its body             202
                │
                ▼  enqueue_sync(trigger=webhook) — one pass per source at a time
        the pass stores it (leka/ingestion/sync.py), then extraction…

ANSWERED IN MILLISECONDS, whatever the pipeline is doing: the sender is told
the delivery was kept, not that it was processed — what every webhook sender
expects, and what lets a burst wait in the inbox rather than time out.

THE DELIVERY IS READ AT THE DOOR as the pass will read it — the same pure
`receive` — so a delivery the pass could not store is refused while its
sender is still listening, with the reason, and logged for the admin.
Refused before the signature is checked, nothing is written: the address is
public, and an unsigned POST must not be able to fill a table.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import structlog

from leka.connectors import (
    ConnectorError,
    Receiver,
    RefusedDeliveryError,
    Source,
    SourceNotFoundError,
    SourceService,
    UnknownConnectorError,
    get_connector,
)
from leka.core import ratelimit
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion.models import DeliveryStatus, SyncTrigger
from leka.ingestion.repository import WebhookDeliveryRepository
from leka.ingestion.sync import SYNCABLE, enqueue_sync

logger = structlog.get_logger(__name__)

MAX_BODY_BYTES = 1_000_000
# What may wait for a pass, per source: beyond, the sender is asked to come
# back — it retries — rather than the inbox growing without end.
MAX_BACKLOG = 1_000
MAX_BACKLOG_BYTES = 50_000_000
BACKLOG_RETRY_SECONDS = 60
# Per source, whatever address it comes from — the API's own limit, per
# address, applies as well (leka/api/ratelimit.py).
SOURCE_LIMIT = ratelimit.Limit(attempts=1_200, window_seconds=60)
# The sender's own id for a delivery, where the usual senders put it.
DELIVERY_ID_HEADERS = (
    "webhook-id",
    "x-github-delivery",
    "x-gitlab-event-uuid",
    "x-delivery-id",
    "x-request-id",
)

# Why a delivery is not kept — the route answers each its own way.
Refused = Literal[
    "unknown", "signature", "stale", "inactive", "busy", "malformed", "unmapped", "too_large"
]


class DeliveryRefusedError(Exception):
    def __init__(self, reason: Refused, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.reason: Refused = reason
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class Accepted:
    """A delivery kept: pending for the pass, or ignored — none of the
    definition's resources is it."""

    delivery: uuid.UUID
    status: Literal["pending", "ignored"]
    resource: str | None
    records: int
    gone: int


async def receive(
    source_id: uuid.UUID,
    headers: Mapping[str, str],
    body: bytes,
    *,
    now: datetime | None = None,
) -> Accepted:
    """One delivery, from the door to the inbox. `headers` named in lower case."""
    now = now or datetime.now(UTC)
    if len(body) > MAX_BODY_BYTES:
        raise DeliveryRefusedError("too_large", f"A delivery is {MAX_BODY_BYTES} bytes at most.")
    with system_scope():
        async with session_factory() as session:
            found = await session.get(Source, source_id)
            workspace_id = found.workspace_id if found is not None else None
    if workspace_id is None:
        raise _unknown(source_id)

    with workspace_scope(workspace_id):
        async with session_factory() as session:
            sources = SourceService(session, workspace_id, actor_user_id=None)
            opened = await _opened(sources, source_id)
            if opened is None:
                raise _unknown(source_id)
            source, connector = opened
            try:
                connector.verify(headers, body, now=now)
            except RefusedDeliveryError as refused:
                logger.warning(
                    "webhook_refused",
                    source_id=str(source_id),
                    reason=refused.reason,
                    size=len(body),
                )
                raise DeliveryRefusedError(refused.reason, refused.message) from None
            if source.status not in SYNCABLE:
                raise DeliveryRefusedError(
                    "inactive", "The source is not switched on: activate it, then send again."
                )
            verdict = await ratelimit.consume("webhook", str(source_id), SOURCE_LIMIT)
            if not verdict.allowed:
                raise DeliveryRefusedError(
                    "busy",
                    "Too many deliveries to this source: send again shortly.",
                    retry_after=verdict.retry_after_seconds,
                )
            deliveries = WebhookDeliveryRepository(session, workspace_id)
            waiting, waiting_bytes = await deliveries.backlog(source_id)
            if waiting >= MAX_BACKLOG or waiting_bytes + len(body) > MAX_BACKLOG_BYTES:
                logger.warning("webhook_backlog_full", source_id=str(source_id), waiting=waiting)
                raise DeliveryRefusedError(
                    "busy",
                    "Deliveries wait to be stored: send again shortly.",
                    retry_after=BACKLOG_RETRY_SECONDS,
                )

            sent_as = _delivery_id(headers)
            try:
                received = connector.receive(body, now=now)
            except RefusedDeliveryError as refused:
                deliveries.keep(
                    source_id=source_id,
                    received_at=now,
                    status=DeliveryStatus.REJECTED,
                    size_bytes=len(body),
                    delivery_id=sent_as,
                    error={"reason": refused.reason, "message": refused.message},
                )
                await session.commit()
                logger.info("webhook_rejected", source_id=str(source_id), reason=refused.reason)
                raise DeliveryRefusedError(refused.reason, refused.message) from None

            status = DeliveryStatus.IGNORED if received.ignored else DeliveryStatus.PENDING
            kept = deliveries.keep(
                source_id=source_id,
                received_at=now,
                status=status,
                size_bytes=len(body),
                delivery_id=sent_as,
                resource=received.resource,
                records=len(received.records),
                gone=len(received.gone),
                body=body,
            )
            await session.commit()

    logger.info(
        "webhook_received",
        source_id=str(source_id),
        status=status.value,
        resource=received.resource,
        records=len(received.records),
        gone=len(received.gone),
    )
    if status is DeliveryStatus.PENDING:
        # Already queued or under way: that pass takes it — it reads the
        # inbox until it is empty.
        await enqueue_sync(workspace_id, source_id, trigger=SyncTrigger.WEBHOOK)
    return Accepted(
        delivery=kept.id,
        status="ignored" if received.ignored else "pending",
        resource=received.resource,
        records=len(received.records),
        gone=len(received.gone),
    )


async def _opened(sources: SourceService, source_id: uuid.UUID) -> tuple[Source, Receiver] | None:
    """The source and its connector — if it is a webhook source whose
    settings and secret can be read. Else None: nothing can be verified, so
    nothing is taken."""
    try:
        source = await sources.get(source_id)
        if not get_connector(source.kind).manifest.receives:
            return None
        connector = await sources.open_connector(source)
    except (SourceNotFoundError, UnknownConnectorError):
        return None
    except ConnectorError as error:
        logger.warning(
            "webhook_source_unusable", source_id=str(source_id), code=error.diagnostic.code.value
        )
        return None
    return (source, connector) if isinstance(connector, Receiver) else None


def _delivery_id(headers: Mapping[str, str]) -> str | None:
    for name in DELIVERY_ID_HEADERS:
        value = headers.get(name, "").strip()
        if value:
            return value[:200]
    return None


def _unknown(source_id: uuid.UUID) -> DeliveryRefusedError:
    logger.info("webhook_unknown_source", source_id=str(source_id))
    return DeliveryRefusedError("unknown", "No webhook source at this address.")
