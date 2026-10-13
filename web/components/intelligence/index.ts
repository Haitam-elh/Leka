/**
 * LEKA's intelligence outputs, as the screens draw them (LEKA-341): the
 * context used, findings and probable causes, evidence and its sources,
 * impact and risk, recommendations and actions, confidence and what is
 * uncertain — and how an analysis went. Shapes in lib/intelligence.ts;
 * when to use each in docs/frontend/intelligence-components.md.
 */

export { AnalysisSummary, AnalysisView } from "@/components/intelligence/analysis";
export { AnalysisState } from "@/components/intelligence/analysis-state";
export {
  AnalysisLimits,
  ConfidenceExplained,
  ConflictList,
  FreshnessNotice,
  NextStepPanel,
  SourcesConsulted,
  UnderstoodLine,
} from "@/components/intelligence/explained";
export {
  ConfidenceBadge,
  ConfidencePanel,
  SupportList,
  UncertaintyList,
} from "@/components/intelligence/confidence";
export {
  ContextUsedPanel,
  ContextVersionLine,
  retrieverName,
} from "@/components/intelligence/context-used";
export {
  EvidenceButton,
  EvidenceList,
  EvidenceStrip,
  EvidenceToggle,
} from "@/components/intelligence/evidence";
export { ExampleNotice } from "@/components/intelligence/example";
export { FindingList, ProbableCauseList } from "@/components/intelligence/findings";
export { ImpactPanel, RiskBadge } from "@/components/intelligence/impact";
export { Pill } from "@/components/intelligence/pill";
export {
  ControlNotice,
  RecommendationCard,
  RecommendationList,
} from "@/components/intelligence/recommendations";
export { IntelligenceSection, type SectionKind } from "@/components/intelligence/section";
