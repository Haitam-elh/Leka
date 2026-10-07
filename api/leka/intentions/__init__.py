"""Intentions: intention -> decision -> action, with human approval.

Top of the dependency chain. The only module allowed to execute an action
against a customer's systems, and only after explicit approval.

An intention (LEKA-384) is kept from the moment someone asks: its words, its
scope, where it stands in its lifecycle (lifecycle.py) — submitted,
analysing, awaiting a decision, approved, scheduled, executing, verifying,
completed; or rejected, failed, cancelled — every change an event of its
history the database refuses to rewrite, and what it is linked to: its
context, findings, entities, and the decisions, actions and outcomes
LEKA-390 to 392 add — and what LEKA understood of it (understanding.py,
LEKA-385): its goal, the actions asked, the things it is about, what is
ambiguous, each with its words; not understood enough, it is said
needs_clarification. docs/intentions.md.
"""

from leka.intentions.lifecycle import (
    CLOSED,
    PHASES,
    TRANSITIONS,
    Actor,
    IllegalTransitionError,
    IntentionStatus,
    Move,
    moves,
    phase,
)
from leka.intentions.models import Intention, IntentionEvent, IntentionLink
from leka.intentions.repository import IntentionFilters, IntentionRepository
from leka.intentions.schemas import (
    ActionRead,
    AmbiguityRead,
    Approval,
    GoalRead,
    IntentionAsked,
    IntentionCounts,
    IntentionCreated,
    IntentionDetail,
    IntentionEventRead,
    IntentionLinkCreate,
    IntentionLinkRead,
    IntentionRead,
    ProposedAction,
    Understanding,
    UnderstoodEntity,
    Withdrawal,
)
from leka.intentions.service import (
    IntentionArchivedError,
    IntentionService,
    LinkRefusedError,
    NothingToStartError,
    NotYoursError,
    intention_read,
)
from leka.intentions.understanding import UNDERSTANDING_VERSION, understand

__all__ = [
    "CLOSED",
    "PHASES",
    "TRANSITIONS",
    "UNDERSTANDING_VERSION",
    "ActionRead",
    "Actor",
    "AmbiguityRead",
    "Approval",
    "GoalRead",
    "IllegalTransitionError",
    "Intention",
    "IntentionArchivedError",
    "IntentionAsked",
    "IntentionCounts",
    "IntentionCreated",
    "IntentionDetail",
    "IntentionEvent",
    "IntentionEventRead",
    "IntentionFilters",
    "IntentionLink",
    "IntentionLinkCreate",
    "IntentionLinkRead",
    "IntentionRead",
    "IntentionRepository",
    "IntentionService",
    "IntentionStatus",
    "LinkRefusedError",
    "Move",
    "NotYoursError",
    "NothingToStartError",
    "ProposedAction",
    "Understanding",
    "UnderstoodEntity",
    "Withdrawal",
    "intention_read",
    "moves",
    "phase",
    "understand",
]
