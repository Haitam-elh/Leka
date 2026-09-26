"""Ingestion: raw payloads in, normalised candidates out.

The middle of the background loop. Depends on leka.connectors; knows nothing
about how the graph is queried or how answers are built.
"""

from leka.ingestion.models import RawPayload, SourceSync, SyncRunStatus
from leka.ingestion.repository import (
    IngestionRunRepository,
    RawPayloadRepository,
    SourceSyncRepository,
)
from leka.ingestion.schemas import NormalisedEntity, NormalisedRelationship
from leka.ingestion.service import IngestionService

__all__ = [
    "IngestionRunRepository",
    "IngestionService",
    "NormalisedEntity",
    "NormalisedRelationship",
    "RawPayload",
    "RawPayloadRepository",
    "SourceSync",
    "SourceSyncRepository",
    "SyncRunStatus",
]
