"""Intelligence: what LEKA concludes from what it knows (LEKA-377).

Analyses run over the company model and the contexts — when the model is
built again, every hour that finds a workspace behind, and when someone
asks — each named, versioned, isolated from the others. Every run is kept
with what each analysis did; every conclusion is a FINDING, kept across
runs under one key, with what shows it and where that was read: opened,
seen again, resolved, reopened.

The frame (analysis.py) is the epic's: LEKA-378 to 383 add their analyses
beside the first ones (rules.py) — change and impact (changes.py, LEKA-378):
which changes matter, what they reach, what followed them; knowledge gaps
(gaps.py, LEKA-379); knowledge enrichment (enrichment.py, LEKA-380), whose
analyses PROPOSE — a relationship, an attribute — kept as CANDIDATES until
validated or rejected, and applied to the model once validated
(curation.py); knowledge conflicts (conflicts.py, LEKA-382): what the
model's sources disagree on, weighed and recommended, settled by someone
(arbitration.py); knowledge quality (quality.py, LEKA-381): how complete,
fresh, consistent and sure what LEKA knows is, each thing and each area,
kept over time (measures.py); knowledge evolution (evolution.py, LEKA-383):
what the model's recent course says — dependencies grown, owners lost,
things gone that others relied on, incidents rising — and what happened,
day by day, for Activité (activity.py). Model-assisted analyses are
declared like the others and skipped, said so, until leka.capabilities
calls a model.

Above leka.capabilities, which a model-assisted analysis will call the
model through, and leka.context; below leka.intentions, which reads what it
concluded through this file (architecture rule 1).
"""

from leka.intelligence.activity import ActivityService
from leka.intelligence.analysis import (
    Analyzer,
    Authority,
    ConflictDraft,
    ContextStanding,
    Draft,
    Evidence,
    Material,
    Method,
    Outcome,
    Proposal,
    QualityScore,
    Reads,
    Severity,
    Subject,
    catalogue_hash,
    execute,
)
from leka.intelligence.arbitration import (
    ArbitrationService,
    conflict_detail,
    conflict_read,
    conflict_reads,
)
from leka.intelligence.curation import (
    DecisionRefusedError,
    EnrichmentService,
    candidate_detail,
    candidate_read,
    candidate_reads,
)
from leka.intelligence.measures import QualityService, quality_read, quality_reads
from leka.intelligence.models import (
    AuthorityRule,
    EnrichmentCandidate,
    Finding,
    IntelligenceRun,
    IntelligenceStep,
    KnowledgeConflict,
    QualityPoint,
    QualityScoreRow,
)
from leka.intelligence.repository import (
    ActivityRepository,
    CandidateFilters,
    ConflictFilters,
    FindingFilters,
    IntelligenceRepository,
    QualityFilters,
    QualityRepository,
)
from leka.intelligence.rules import ANALYZERS, analyzer_named
from leka.intelligence.schemas import (
    ActivityRead,
    AnalysisRequest,
    AnalysisRequested,
    AnalyzerRead,
    Arbitration,
    AuthorityRuleCreate,
    AuthorityRuleRead,
    CandidateDetail,
    CandidateRead,
    ChangeImpactDetail,
    ChangeImpactRead,
    ChangeImpactTimeline,
    ConflictDetail,
    ConflictRead,
    ConflictSummary,
    Decision,
    Dismissal,
    EnrichmentSummary,
    EvidenceRead,
    FindingDetail,
    FindingRead,
    FollowedRead,
    ImpactRead,
    IntelligenceSummary,
    KnowledgeQualityDetail,
    KnowledgeQualityPoint,
    KnowledgeQualityRead,
    KnowledgeQualitySummary,
    Reprocessed,
    RunDetail,
    RunRead,
    StepRead,
    SubjectRead,
)
from leka.intelligence.service import IntelligenceService, UnknownAnalyzerError

__all__ = [
    "ANALYZERS",
    "ActivityRead",
    "ActivityRepository",
    "ActivityService",
    "AnalysisRequest",
    "AnalysisRequested",
    "Analyzer",
    "AnalyzerRead",
    "Arbitration",
    "ArbitrationService",
    "Authority",
    "AuthorityRule",
    "AuthorityRuleCreate",
    "AuthorityRuleRead",
    "CandidateDetail",
    "CandidateFilters",
    "CandidateRead",
    "ChangeImpactDetail",
    "ChangeImpactRead",
    "ChangeImpactTimeline",
    "ConflictDetail",
    "ConflictDraft",
    "ConflictFilters",
    "ConflictRead",
    "ConflictSummary",
    "ContextStanding",
    "Decision",
    "DecisionRefusedError",
    "Dismissal",
    "Draft",
    "EnrichmentCandidate",
    "EnrichmentService",
    "EnrichmentSummary",
    "Evidence",
    "EvidenceRead",
    "Finding",
    "FindingDetail",
    "FindingFilters",
    "FindingRead",
    "FollowedRead",
    "ImpactRead",
    "IntelligenceRepository",
    "IntelligenceRun",
    "IntelligenceService",
    "IntelligenceStep",
    "IntelligenceSummary",
    "KnowledgeConflict",
    "KnowledgeQualityDetail",
    "KnowledgeQualityPoint",
    "KnowledgeQualityRead",
    "KnowledgeQualitySummary",
    "Material",
    "Method",
    "Outcome",
    "Proposal",
    "QualityFilters",
    "QualityPoint",
    "QualityRepository",
    "QualityScore",
    "QualityScoreRow",
    "QualityService",
    "Reads",
    "Reprocessed",
    "RunDetail",
    "RunRead",
    "Severity",
    "StepRead",
    "Subject",
    "SubjectRead",
    "UnknownAnalyzerError",
    "analyzer_named",
    "candidate_detail",
    "candidate_read",
    "candidate_reads",
    "catalogue_hash",
    "conflict_detail",
    "conflict_read",
    "conflict_reads",
    "execute",
    "quality_read",
    "quality_reads",
]
