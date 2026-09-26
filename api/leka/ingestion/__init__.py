"""Ingestion: raw payloads in, normalised candidates out.

The middle of the background loop. Depends on leka.connectors; knows nothing
about how the graph is queried or how answers are built.
"""

from leka.ingestion.models import (
    RawPayload,
    SourceSync,
    SyncRun,
    SyncRunOutcome,
    SyncRunStatus,
    SyncTrigger,
)
from leka.ingestion.repository import (
    IngestionRunRepository,
    RawPayloadRepository,
    SourceSyncRepository,
    SyncRunRepository,
)
from leka.ingestion.schemas import (
    NormalisedEntity,
    NormalisedRelationship,
    SourceSyncRead,
    SourceSyncs,
    SyncRequested,
    SyncRunRead,
    SyncSummary,
)
from leka.ingestion.service import IngestionService

__all__ = [
    "IngestionRunRepository",
    "IngestionService",
    "NormalisedEntity",
    "NormalisedRelationship",
    "RawPayload",
    "RawPayloadRepository",
    "SourceSync",
    "SourceSyncRead",
    "SourceSyncRepository",
    "SourceSyncs",
    "SyncRequested",
    "SyncRun",
    "SyncRunOutcome",
    "SyncRunRead",
    "SyncRunRepository",
    "SyncRunStatus",
    "SyncSummary",
    "SyncTrigger",
]
