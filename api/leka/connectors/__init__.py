"""Connectors: one subpackage per customer system, plus the shared base.

Bottom of the dependency chain. Depends on leka.core, leka.db and
leka.platform — never on ingestion, knowledge, context or intentions
(architecture rule 1).
"""

from leka.connectors.models import Source, SourceKind, SourceStatus

__all__ = ["Source", "SourceKind", "SourceStatus"]
