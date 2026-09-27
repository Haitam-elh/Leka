"""The checksum of a record's payload — what the index deduplicates on and
what extraction knows a record by (LEKA-353, LEKA-354).

In a module of its own: the sync and the extraction both need it, and the
sync queues the extraction.
"""

from __future__ import annotations

import hashlib
import json

from leka.connectors import RawRecord


def checksum(record: RawRecord) -> str:
    """sha256 of the payload's canonical JSON — keys sorted, no spacing — so
    the same object read twice has the same checksum. A vendor field that
    changes on every read (a signed URL) defeats it for that record, which
    costs a write, not a wrong answer."""
    canonical = json.dumps(record.payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
