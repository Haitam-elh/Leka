"use client";

import { AnalysisState } from "@/components/intelligence/analysis-state";
import { ConfidenceBadge, UncertaintyList } from "@/components/intelligence/confidence";
import { FindingList, ProbableCauseList } from "@/components/intelligence/findings";
import { ImpactPanel } from "@/components/intelligence/impact";
import { RecommendationList } from "@/components/intelligence/recommendations";
import { IntelligenceSection } from "@/components/intelligence/section";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Analysis } from "@/lib/intelligence";

/**
 * An analysis, whole, in the one order every intelligence output keeps
 * (LEKA-341): how it went; how sure it is as a whole; what is known (the
 * facts); what is thought (the probable causes); what it reaches; what
 * LEKA proposes — apart, below; what it does not know. Evidence opens from
 * each statement. A screen gives it an Analysis; it draws nothing else.
 */
export function AnalysisView({
  analysis,
  onRetry,
  proposals = true,
}: {
  analysis: Analysis;
  onRetry?: () => void;
  /** Whether the proposals' section is drawn, even empty. */
  proposals?: boolean;
}) {
  const t = useDictionary();
  const w = t.intelligence;
  return (
    <div className="space-y-4" data-testid="analysis" data-status={analysis.status}>
      <AnalysisState status={analysis.status} missing={analysis.missing} onRetry={onRetry} />
      {analysis.status === "failed" || analysis.status === "pending" ? null : (
        <>
          <p className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-shell-muted">
            {w.overall}
            <ConfidenceBadge score={analysis.confidence} />
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            <IntelligenceSection kind="fact" title={w.findings.title}>
              <FindingList findings={analysis.findings} />
            </IntelligenceSection>
            <IntelligenceSection kind="hypothesis" title={w.causes.title}>
              <ProbableCauseList causes={analysis.causes} />
            </IntelligenceSection>
          </div>
          <IntelligenceSection kind="fact" title={w.impact.title}>
            <ImpactPanel impact={analysis.impact} />
          </IntelligenceSection>
          {proposals ? (
            <IntelligenceSection kind="proposal" title={w.recommendations.title}>
              <RecommendationList recommendations={analysis.recommendations} />
            </IntelligenceSection>
          ) : null}
          <UncertaintyList items={analysis.uncertainties} />
        </>
      )}
    </div>
  );
}
