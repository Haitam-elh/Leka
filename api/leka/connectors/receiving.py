"""What a source that is sent to, rather than read, adds to the contract
(LEKA-350): a webhook.

A connector reads its vendor — the sync asks, page by page. A RECEIVER is
the other way round: the system sends LEKA what changed, when it changes,
to an address of the source's own (POST /api/v1/webhooks/sources/{id}).
Two things only the connector can say, from its settings and its secret:

    verify    whether a delivery is the system's — its signature, checked
              against the secret before anything else is done with it
    receive   what a delivery holds: records to store, and ids gone

RECEIVING IS NOT STORING. The route verifies, keeps the delivery and
answers; the source's next pass stores what it holds — one pass at a time
per source, as every pass (leka/ingestion/sync.py). So a record received is
stored exactly as a record read: the index, the deduplication, the
retention, extraction after. And never while another pass writes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from leka.connectors.schemas import RawRecord

# Why a delivery is refused — the route answers each its own way:
#   signature  not the system's: no signature, or a wrong one        401
#   stale      signed too long ago, or in the future: a replay?      401
#   malformed  not JSON, or not what the definition says it holds    400
#   unmapped   a record the mapping cannot read: no id, no title     422
Refusal = Literal["signature", "stale", "malformed", "unmapped"]


class RefusedDeliveryError(Exception):
    """A delivery the receiver will not take, and why, in words the sender
    can act on — never the secret, never the body."""

    def __init__(self, reason: Refusal, message: str) -> None:
        super().__init__(message)
        self.reason: Refusal = reason
        self.message = message


@dataclass(frozen=True)
class Received:
    """What one delivery holds."""

    # The resource it is — the first whose `match` it meets. None: none is,
    # and it is ignored: a system sends events nobody asked LEKA to keep.
    resource: str | None
    records: list[RawRecord] = field(default_factory=list)
    # The external ids the system says are deleted.
    gone: list[str] = field(default_factory=list)

    @property
    def ignored(self) -> bool:
        return self.resource is None


class Receiver(ABC):
    """A connector the system sends to. Its manifest says `receives`."""

    @abstractmethod
    def verify(self, headers: Mapping[str, str], body: bytes, *, now: datetime) -> None:
        """Raise RefusedDeliveryError unless the delivery is signed with the
        source's secret. `headers` are named in lower case; `body` is the
        bytes as they came — a signature is over those, not over a parse."""

    @abstractmethod
    def receive(self, body: bytes, *, now: datetime) -> Received:
        """What a verified delivery holds, or RefusedDeliveryError. Pure: the
        same body gives the same records, at the door and in the pass."""
