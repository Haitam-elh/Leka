"""Connectors: one subpackage per customer system, plus the shared base.

Bottom of the dependency chain. Depends on leka.core, leka.db and
leka.platform — never on ingestion, knowledge, context or intentions
(architecture rule 1).

A connector's job stops at fetching. It does not interpret, normalise or
store: that is leka.ingestion.
"""

from leka.connectors.models import Source, SourceKind, SourceStatus
from leka.connectors.repository import SourceCredentialSweeper, SourceRepository
from leka.connectors.schemas import RawRecord, SyncResult
from leka.connectors.service import SourceService

__all__ = [
    "RawRecord",
    "Source",
    "SourceCredentialSweeper",
    "SourceKind",
    "SourceRepository",
    "SourceService",
    "SourceStatus",
    "SyncResult",
]
