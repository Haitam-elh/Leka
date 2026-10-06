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
(curation.py). Model-assisted analyses are declared like the others and
skipped, said so, until leka.capabilities calls a model.

Above leka.capabilities, which a model-assisted analysis will call the
model through, and leka.context; below leka.intentions, which reads what it
concluded through this file (architecture rule 1).
"""

from leka.intelligence.analysis import (
    Analyzer,
    ContextStanding,
    Draft,
    Evidence,
    Material,
    Method,
    Outcome,
    Proposal,
    Reads,
    Severity,
    Subject,
    catalogue_hash,
    execute,
)
from leka.intelligence.curation import (
    DecisionRefusedError,
    EnrichmentService,
    candidate_detail,
    candidate_read,
    candidate_reads,
)
from leka.intelligence.models import (
    EnrichmentCandidate,
    Finding,
    IntelligenceRun,
    IntelligenceStep,
)
from leka.intelligence.repository import (
    CandidateFilters,
    FindingFilters,
    IntelligenceRepository,
)
from leka.intelligence.rules import ANALYZERS, analyzer_named
from leka.intelligence.schemas import (
    AnalysisRequest,
    AnalysisRequested,
    AnalyzerRead,
    CandidateDetail,
    CandidateRead,
    ChangeImpactDetail,
    ChangeImpactRead,
    ChangeImpactTimeline,
    Decision,
    EnrichmentSummary,
    EvidenceRead,
    FindingDetail,
    FindingRead,
    FollowedRead,
    ImpactRead,
    IntelligenceSummary,
    Reprocessed,
    RunDetail,
    RunRead,
    StepRead,
    SubjectRead,
)
from leka.intelligence.service import IntelligenceService, UnknownAnalyzerError

__all__ = [
    "ANALYZERS",
    "AnalysisRequest",
    "AnalysisRequested",
    "Analyzer",
    "AnalyzerRead",
    "CandidateDetail",
    "CandidateFilters",
    "CandidateRead",
    "ChangeImpactDetail",
    "ChangeImpactRead",
    "ChangeImpactTimeline",
    "ContextStanding",
    "Decision",
    "DecisionRefusedError",
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
    "Material",
    "Method",
    "Outcome",
    "Proposal",
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
    "execute",
]
