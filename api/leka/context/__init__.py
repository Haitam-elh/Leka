"""Context: what LEKA assembles to understand a request in its company
context (LEKA-370) — made from the company model, kept version by version,
each piece with where it came from; found by retrievers combined — the
graph, words in the model and in the records' text, time, ways between
things — each saying how relevant (LEKA-371).

Reads state the background loop prepared. Calls no customer API — by the
time a question arrives, the work is done.
"""

from leka.context.models import Context, ContextElement, ContextVersion
from leka.context.repository import ContextFilters, ContextRepository
from leka.context.schemas import (
    CONTRACT_VERSION,
    RETRIEVERS,
    AssembledContext,
    ContextCreate,
    ContextDetail,
    ContextDiff,
    ContextElementRead,
    ContextRead,
    ContextRefresh,
    ContextRequest,
    ContextStatus,
    ContextSubject,
    ContextVersionRead,
    RefreshOutcome,
    RetrieverName,
    RetrieverRunRead,
    SubjectType,
)
from leka.context.service import ContextArchivedError, ContextService
from leka.context.strategies import STRATEGIES, Strategy

__all__ = [
    "CONTRACT_VERSION",
    "RETRIEVERS",
    "STRATEGIES",
    "AssembledContext",
    "Context",
    "ContextArchivedError",
    "ContextCreate",
    "ContextDetail",
    "ContextDiff",
    "ContextElement",
    "ContextElementRead",
    "ContextFilters",
    "ContextRead",
    "ContextRefresh",
    "ContextRepository",
    "ContextRequest",
    "ContextService",
    "ContextStatus",
    "ContextSubject",
    "ContextVersion",
    "ContextVersionRead",
    "RefreshOutcome",
    "RetrieverName",
    "RetrieverRunRead",
    "Strategy",
    "SubjectType",
]
