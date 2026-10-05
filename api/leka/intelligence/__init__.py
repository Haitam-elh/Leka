"""Intelligence: what LEKA concludes from what it knows (LEKA-377).

Analyses run over the company model and the contexts — when the model is
built again, every hour that finds a workspace behind, and when someone
asks — each named, versioned, isolated from the others. Every run is kept
with what each analysis did; every conclusion is a FINDING, kept across
runs under one key, with what shows it and where that was read: opened,
seen again, resolved, reopened.

The frame (analysis.py) is the epic's: LEKA-378 to 383 add their analyses
beside the first ones (rules.py). Model-assisted analyses are declared like
the others and skipped, said so, until leka.capabilities calls a model.

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
    Reads,
    Severity,
    Subject,
    catalogue_hash,
    execute,
)
from leka.intelligence.models import Finding, IntelligenceRun, IntelligenceStep
from leka.intelligence.repository import FindingFilters, IntelligenceRepository
from leka.intelligence.rules import ANALYZERS, analyzer_named
from leka.intelligence.schemas import (
    AnalysisRequest,
    AnalysisRequested,
    AnalyzerRead,
    EvidenceRead,
    FindingDetail,
    FindingRead,
    IntelligenceSummary,
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
    "ContextStanding",
    "Draft",
    "Evidence",
    "EvidenceRead",
    "Finding",
    "FindingDetail",
    "FindingFilters",
    "FindingRead",
    "IntelligenceRepository",
    "IntelligenceRun",
    "IntelligenceService",
    "IntelligenceStep",
    "IntelligenceSummary",
    "Material",
    "Method",
    "Outcome",
    "Reads",
    "RunDetail",
    "RunRead",
    "Severity",
    "StepRead",
    "Subject",
    "SubjectRead",
    "UnknownAnalyzerError",
    "analyzer_named",
    "catalogue_hash",
    "execute",
]
