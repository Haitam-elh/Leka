"""Ingestion: raw payloads in, normalised candidates out.

The middle of the background loop. Depends on leka.connectors; knows nothing
about how the graph is queried or how answers are built.
"""

from leka.ingestion.models import (
    ExtractedRecordRow,
    ExtractionStatus,
    RawPayload,
    SourceRecord,
    SourceSync,
    SyncRun,
    SyncRunOutcome,
    SyncRunStatus,
    SyncTrigger,
)
from leka.ingestion.repository import (
    ExtractionRepository,
    IngestionRunRepository,
    RawPayloadRepository,
    SourceRecordRepository,
    SourceSyncRepository,
    SyncRunRepository,
)
from leka.ingestion.schemas import (
    ExtractionFailureRead,
    ExtractorCount,
    NormalisedEntity,
    NormalisedRelationship,
    SourceExtraction,
    SourceSyncRead,
    SourceSyncs,
    SyncRequested,
    SyncRunRead,
    SyncSummary,
)
from leka.ingestion.service import IngestionService

__all__ = [
    "ExtractedRecordRow",
    "ExtractionFailureRead",
    "ExtractionRepository",
    "ExtractionStatus",
    "ExtractorCount",
    "IngestionRunRepository",
    "IngestionService",
    "NormalisedEntity",
    "NormalisedRelationship",
    "RawPayload",
    "RawPayloadRepository",
    "SourceExtraction",
    "SourceRecord",
    "SourceRecordRepository",
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
