"""Context: what LEKA assembles to understand a request in its company
context (LEKA-370) — made from the company model, kept version by version,
each piece with where it came from; found by retrievers combined — the
graph, words in the model and in the records' text, time, ways between
things — each saying how relevant (LEKA-371); ranked, duplicates folded,
conflicts said (LEKA-372); for an intention, what it asks for, read from
its words, and what is missing (LEKA-373); and kept up with the company —
behind the model said, made again when in use, widened, narrowed, asked
again, every recalculation traced (LEKA-374); and judged — complete,
fresh, to be relied on, what it lacks, what it disagrees on and how badly
— with what people say of it (LEKA-375).

Reads state the background loop prepared. Calls no customer API — by the
time a question arrives, the work is done.
"""

from leka.context.intent import kinds_said
from leka.context.models import (
    Context,
    ContextCheck,
    ContextElement,
    ContextFeedback,
    ContextVersion,
)
from leka.context.repository import ContextFilters, ContextRepository
from leka.context.schemas import (
    CONTRACT_HEADER,
    CONTRACT_VERSION,
    RETRIEVERS,
    SUPPORTED_CONTRACTS,
    AssembledContext,
    ContextChange,
    ContextCheckRead,
    ContextCompress,
    ContextContract,
    ContextCreate,
    ContextDetail,
    ContextDiff,
    ContextElementRead,
    ContextExpand,
    ContextFeedbackCreate,
    ContextFeedbackRead,
    ContextFreshness,
    ContextQuality,
    ContextRead,
    ContextRefresh,
    ContextRequest,
    ContextStatus,
    ContextSubject,
    ContextUpdate,
    ContextVersionRead,
    ElementEvidence,
    ElementInspection,
    IntentAsk,
    IntentGap,
    IntentPlan,
    QualityInspection,
    RefreshOutcome,
    RetrievalFeedback,
    RetrieverName,
    RetrieverRunRead,
    SubjectType,
)
from leka.context.service import (
    ContextArchivedError,
    ContextRefusedError,
    ContextRootError,
    ContextService,
    NotAnIntentionError,
)
from leka.context.strategies import STRATEGIES, Strategy

__all__ = [
    "CONTRACT_HEADER",
    "CONTRACT_VERSION",
    "RETRIEVERS",
    "STRATEGIES",
    "SUPPORTED_CONTRACTS",
    "AssembledContext",
    "Context",
    "ContextArchivedError",
    "ContextChange",
    "ContextCheck",
    "ContextCheckRead",
    "ContextCompress",
    "ContextContract",
    "ContextCreate",
    "ContextDetail",
    "ContextDiff",
    "ContextElement",
    "ContextElementRead",
    "ContextExpand",
    "ContextFeedback",
    "ContextFeedbackCreate",
    "ContextFeedbackRead",
    "ContextFilters",
    "ContextFreshness",
    "ContextQuality",
    "ContextRead",
    "ContextRefresh",
    "ContextRefusedError",
    "ContextRepository",
    "ContextRequest",
    "ContextRootError",
    "ContextService",
    "ContextStatus",
    "ContextSubject",
    "ContextUpdate",
    "ContextVersion",
    "ContextVersionRead",
    "ElementEvidence",
    "ElementInspection",
    "IntentAsk",
    "IntentGap",
    "IntentPlan",
    "NotAnIntentionError",
    "QualityInspection",
    "RefreshOutcome",
    "RetrievalFeedback",
    "RetrieverName",
    "RetrieverRunRead",
    "Strategy",
    "SubjectType",
    "kinds_said",
]
