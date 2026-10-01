"""Extraction (LEKA-354): a stored vendor record in, structured content out.

Importing the package registers every strategy. Contract: docs/extraction.md.
"""

from leka.ingestion.extraction import (  # noqa: F401 — importing registers the strategies
    cloud,
    code,
    custom,
    data,
    documents,
    observability,
    people,
    projects,
    tickets,
)
from leka.ingestion.extraction.contract import (
    MAX_TEXT,
    Content,
    Extracted,
    ExtractedRecord,
    Extraction,
    ExtractionFailure,
    FailureCode,
    Provenance,
    Reference,
)
from leka.ingestion.extraction.engine import MalformedPayloadError, extract, strategy_for, supported

__all__ = [
    "MAX_TEXT",
    "Content",
    "Extracted",
    "ExtractedRecord",
    "Extraction",
    "ExtractionFailure",
    "FailureCode",
    "MalformedPayloadError",
    "Provenance",
    "Reference",
    "extract",
    "strategy_for",
    "supported",
]
