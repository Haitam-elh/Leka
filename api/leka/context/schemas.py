"""Types the context module exposes.

An assembled context is what the interactive loop hands to a model. Every
piece of it carries where it came from, because an answer without evidence
is a guess with better grammar.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    """One fact, and where it was observed."""

    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID
    source_id: uuid.UUID
    excerpt: str
    observed_at: datetime | None
    confidence: float = Field(ge=0.0, le=1.0)


class AssembledContext(BaseModel):
    """Everything an agent needs, already retrieved and ranked.

    Assembled from what the background loop prepared. Nothing here triggers
    a call to a customer's API.
    """

    model_config = ConfigDict(frozen=True)

    question: str
    evidence: list[Evidence] = Field(default_factory=list)
    truncated: bool = False
