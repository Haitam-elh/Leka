"""Types the connectors module exposes to the rest of the codebase.

A connector returns RawRecord objects. Deliberately untyped payloads: the
vendor decides their shape, and pretending otherwise puts vendor-specific
knowledge in a module that should not have it. Turning a payload into an
entity is leka.ingestion's job.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RawRecord(BaseModel):
    """One object as its source described it, untouched."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    external_id: str
    kind: str
    payload: dict[str, object]
    fetched_at: datetime


class SyncResult(BaseModel):
    """What one pass over a source produced."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    records: int
    started_at: datetime
    finished_at: datetime
    error: str | None = None
