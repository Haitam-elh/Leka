"""Context: retrieval, ranking, and assembly of what an answer needs.

Reads state the background loop prepared. Calls no customer API — by the
time a question arrives, the work is done.
"""

from leka.context.repository import ContextRepository
from leka.context.schemas import AssembledContext, Evidence
from leka.context.service import ContextService

__all__ = [
    "AssembledContext",
    "ContextRepository",
    "ContextService",
    "Evidence",
]
