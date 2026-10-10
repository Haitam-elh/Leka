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
needs_clarification — and analysed (processing.py, LEKA-388): the
capabilities its goal calls for run on its context, each isolated, the
result kept with every piece of evidence and where it came from — and,
when it asks to act, put to people's decision (approval.py, LEKA-390):
approved, rejected, modified, under the workspace's policy, every vote
kept — and governed (governance.py, oversight.py, LEKA-404): risk classified
by rules, approvals by role, delegation, freezes and waivers, approvals that
expire, decisions escalated, every change in an append-only trail.
docs/intentions.md, docs/governance-rules.md.
"""

from leka.intentions.actions import (
    ActionService,
    EndpointService,
    PlanRefusedError,
    endpoint_read,
    queue_plan,
)
from leka.intentions.approval import (
    DecisionClosedError,
    DecisionRefusedError,
    DecisionService,
    policy_read,
)
from leka.intentions.decisions import Change, PolicyError, Verdict
from leka.intentions.grounding import readiness, refined
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
from leka.intentions.models import (
    ActionEndpoint,
    Intention,
    IntentionAnalysis,
    IntentionDecision,
    IntentionDecisionVote,
    IntentionEvent,
    IntentionLink,
)
from leka.intentions.oversight import ExceptionAsk, OversightRefusedError, OversightService
from leka.intentions.processing import queue_analysis
from leka.intentions.reading import ModelReading
from leka.intentions.repository import IntentionFilters, IntentionRepository
from leka.intentions.routing import query_of, route_intention
from leka.intentions.schemas import (
    ActionEndpointCreate,
    ActionEndpointCreated,
    ActionEndpointRead,
    ActionEndpointUpdate,
    ActionRead,
    AmbiguityRead,
    Approval,
    ApprovalPolicyRead,
    ApprovalPolicyUpdate,
    ContextReadiness,
    DecisionQueuePage,
    DecisionRead,
    DecisionSummary,
    DecisionVoteRequest,
    DelegationCreate,
    DelegationRead,
    ExpectationRead,
    ExpectationReport,
    ExpectationsUpdate,
    GoalRead,
    GovernanceEventRead,
    GovernanceExceptionCreate,
    GovernanceExceptionRead,
    IntentionAnalysisRead,
    IntentionAnalysisRequested,
    IntentionAsked,
    IntentionContext,
    IntentionCounts,
    IntentionCreated,
    IntentionDetail,
    IntentionEventRead,
    IntentionLinkCreate,
    IntentionLinkRead,
    IntentionPlanRead,
    IntentionRead,
    IntentionVerificationRead,
    PlanCancelRequest,
    PlanStartRequest,
    PolicyProbe,
    PolicyVerdictRead,
    ProposedAction,
    ReadinessIssue,
    StepReportRequest,
    TimelineItem,
    Understanding,
    UnderstoodEntity,
    VerificationConclude,
    Withdrawal,
)
from leka.intentions.service import (
    IntentionArchivedError,
    IntentionService,
    LinkRefusedError,
    NothingToStartError,
    NotYoursError,
    analysis_read,
    intention_read,
)

# LEKA's reads, registered as skills (LEKA-396) when this is imported.
from leka.intentions.skills import SKILLS
from leka.intentions.timeline import CATEGORIES, Filters, categories_of, timeline
from leka.intentions.understanding import UNDERSTANDING_VERSION, understand
from leka.intentions.usage import (
    Usage,
    Use,
    WorkspaceUsageRead,
    capability_usage,
    workspace_usage,
)
from leka.intentions.verification import VerificationRefusedError, VerificationService
from leka.intentions.workflow_steps import rules_step

__all__ = [
    "CATEGORIES",
    "CLOSED",
    "PHASES",
    "SKILLS",
    "TRANSITIONS",
    "UNDERSTANDING_VERSION",
    "ActionEndpoint",
    "ActionEndpointCreate",
    "ActionEndpointCreated",
    "ActionEndpointRead",
    "ActionEndpointUpdate",
    "ActionRead",
    "ActionService",
    "Actor",
    "AmbiguityRead",
    "Approval",
    "ApprovalPolicyRead",
    "ApprovalPolicyUpdate",
    "Change",
    "ContextReadiness",
    "DecisionClosedError",
    "DecisionQueuePage",
    "DecisionRead",
    "DecisionRefusedError",
    "DecisionService",
    "DecisionSummary",
    "DecisionVoteRequest",
    "DelegationCreate",
    "DelegationRead",
    "EndpointService",
    "ExceptionAsk",
    "ExpectationRead",
    "ExpectationReport",
    "ExpectationsUpdate",
    "Filters",
    "GoalRead",
    "GovernanceEventRead",
    "GovernanceExceptionCreate",
    "GovernanceExceptionRead",
    "IllegalTransitionError",
    "Intention",
    "IntentionAnalysis",
    "IntentionAnalysisRead",
    "IntentionAnalysisRequested",
    "IntentionArchivedError",
    "IntentionAsked",
    "IntentionContext",
    "IntentionCounts",
    "IntentionCreated",
    "IntentionDecision",
    "IntentionDecisionVote",
    "IntentionDetail",
    "IntentionEvent",
    "IntentionEventRead",
    "IntentionFilters",
    "IntentionLink",
    "IntentionLinkCreate",
    "IntentionLinkRead",
    "IntentionPlanRead",
    "IntentionRead",
    "IntentionRepository",
    "IntentionService",
    "IntentionStatus",
    "IntentionVerificationRead",
    "LinkRefusedError",
    "ModelReading",
    "Move",
    "NotYoursError",
    "NothingToStartError",
    "OversightRefusedError",
    "OversightService",
    "PlanCancelRequest",
    "PlanRefusedError",
    "PlanStartRequest",
    "PolicyError",
    "PolicyProbe",
    "PolicyVerdictRead",
    "ProposedAction",
    "ReadinessIssue",
    "StepReportRequest",
    "TimelineItem",
    "Understanding",
    "UnderstoodEntity",
    "Usage",
    "Use",
    "Verdict",
    "VerificationConclude",
    "VerificationRefusedError",
    "VerificationService",
    "Withdrawal",
    "WorkspaceUsageRead",
    "analysis_read",
    "capability_usage",
    "categories_of",
    "endpoint_read",
    "intention_read",
    "moves",
    "phase",
    "policy_read",
    "query_of",
    "queue_analysis",
    "queue_plan",
    "readiness",
    "refined",
    "route_intention",
    "rules_step",
    "timeline",
    "understand",
    "workspace_usage",
]
