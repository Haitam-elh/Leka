"""Types ingestion exposes.

The pipeline is collect -> extract -> parse -> normalise. What comes out is a
NormalisedEntity: still a candidate, not yet a row. leka.knowledge decides
whether it becomes one.

`type` is a plain string here, not knowledge's EntityType enum, and that is
the dependency rule doing its job rather than an oversight. Dependencies run
knowledge -> ingestion; importing the enum would point them the other way.
The graph's vocabulary belongs to leka.knowledge, which maps these strings
and rejects the ones it does not recognise. Ingestion normalises shapes; it
does not decide what a thing *is*.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NormalisedEntity(BaseModel):
    """A candidate entity, ready for the graph but not yet in it."""

    model_config = ConfigDict(frozen=True)

    type: str
    external_id: str
    source_id: uuid.UUID
    name: str
    attributes: dict[str, object] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    observed_at: datetime


class NormalisedRelationship(BaseModel):
    """A candidate edge, expressed in external ids.

    Ingestion does not know internal ids: it has not written the entities
    yet. Resolving these to rows is leka.knowledge's job.
    """

    model_config = ConfigDict(frozen=True)

    type: str
    from_external_id: str
    to_external_id: str
    source_id: uuid.UUID
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
