"""What normalisation hands to the graph — the contract of LEKA-356.

One extracted record and its parse in, a NormalisedRecord or a
NormalisationFailure out; never an exception. A NormalisedRecord is
candidates in LEKA's common structures: the record's own entity, the people,
services and teams it names, and the relationships between them — every one
with a canonical key, canonical attributes, and the provenance it came from.

Candidates, not rows: deciding that two candidates are one entity is entity
resolution's (LEKA-357), writing them is leka.knowledge's. Rules in
docs/normalisation.md.
"""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from leka.ingestion.extraction import Provenance
from leka.ingestion.schemas import NormalisedEntity, NormalisedRelationship


class NormalisedRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["normalised"] = "normalised"
    provenance: Provenance
    extractor_version: int
    parser_version: int
    normaliser_version: int
    entity: NormalisedEntity = Field(description="The record itself, as an entity.")
    related: list[NormalisedEntity] = Field(
        default_factory=list,
        description="What it names that is an entity too: people, services, teams.",
    )
    relationships: list[NormalisedRelationship] = Field(default_factory=list)
    diagnostics: list[str] = Field(
        default_factory=list, description="What was kept as the vendor said it: an unknown state, …"
    )


class NormalisationFailureCode(enum.StrEnum):
    UNSUPPORTED = "unsupported"  # no mapping for this kind of record
    INVALID = "invalid"  # it cannot be an entity: no name, no identity
    MALFORMED = "malformed"  # its inputs are not an extraction and a parse


class NormalisationFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["failed"] = "failed"
    provenance: Provenance | None
    normaliser_version: int
    code: NormalisationFailureCode
    message: str = Field(description="What was wrong — never a value from the record.")


Normalised = NormalisedRecord | NormalisationFailure
