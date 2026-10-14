"use client";

import { Lightbulb } from "lucide-react";
import { useId } from "react";

import { cn } from "cn";

import { IconTile } from "@/components/environment/parts";
import { AnalysisState } from "@/components/intelligence/analysis-state";
import {
  ConfidenceBadge,
  ConfidencePanel,
  SupportList,
  UncertaintyList,
} from "@/components/intelligence/confidence";
import { EvidenceList } from "@/components/intelligence/evidence";
import { Folded } from "@/components/intelligence/folded";
import {
  AnalysisLimits,
  ConfidenceExplained,
  ConflictList,
  FreshnessNotice,
  NextStepPanel,
  SourcesConsulted,
  UnderstoodLine,
} from "@/components/intelligence/explained";
import {
  FindingList,
  ProbableCauseList,
} from "@/components/intelligence/findings";
import { ImpactPanel } from "@/components/intelligence/impact";
import { RecommendationList } from "@/components/intelligence/recommendations";
import { IntelligenceSection } from "@/components/intelligence/section";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { type Analysis, evidenceOf } from "@/lib/intelligence";

/**
 * An analysis, whole, laid out as mockup 04's "Résultats" (LEKA-341), in
 * the one order every intelligence output keeps: how it went; what it
 * comes to and how sure — the synthesis, its confidence and what that
 * rests on; then, on the left, what is known (the facts), what is thought
 * (the probable causes) and the evidence behind them all; on the right,
 * what it reaches, what LEKA proposes — apart — and what it does not know.
 * One column under 1280 px, in that same order. Evidence opens from each
 * statement. A screen gives it an Analysis; it draws nothing else.
 */

/** Mockup 04's "Synthèse de l'analyse": what it comes to, how sure, on
 * what. */
export function AnalysisSummary({
  analysis,
  level = 3,
  action,
  said,
}: {
  analysis: Analysis;
  level?: 2 | 3;
  /** Under the confidence: "Voir le détail de l'analyse". */
  action?: React.ReactNode;
  /** What it comes to, when more than a sentence says it: a model's
   * answer, its points and caveats (LEKA-394). */
  said?: React.ReactNode;
}) {
  const t = useDictionary();
  const w = t.intelligence.summary;
  const id = useId();
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <section
      aria-labelledby={id}
      className="grid gap-4 rounded-xl border border-shell-line bg-white p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,17rem)]"
      data-testid="analysis-summary"
    >
      <div className="flex items-start gap-3">
        <IconTile icon={Lightbulb} tone="violet" className="size-11" />
        <div className="min-w-0">
          <Heading
            id={id}
            className="text-[1.0625rem] font-semibold tracking-[-0.01em] text-brand-navy"
          >
            {w.title}
          </Heading>
          {said}
          {said && !analysis.summary ? null : (
            // LEKA's own sentence: what each capability concluded — under a
            // model's answer, what that answer was written from.
            <p
              className={cn(
                "text-[0.8125rem] text-shell-muted",
                said ? "mt-2" : "mt-1",
              )}
            >
              {analysis.summary ?? w.none}
            </p>
          )}
        </div>
      </div>
      <div className="space-y-3 md:border-s md:border-shell-line md:ps-4">
        <ConfidenceBadge
          score={analysis.confidence}
          // How sure, as the analysis says it and why (LEKA-441): a word.
          level={analysis.explanation?.confidence.level ?? null}
        />
        <SupportList items={analysis.support ?? []} />
        {action}
      </div>
    </section>
  );
}

export function AnalysisView({
  analysis,
  onRetry,
  proposals = true,
  synthesis = true,
  said,
  next,
  again,
  folded,
  level = 3,
}: {
  analysis: Analysis;
  /** Its findings, evidence, impact and limits folded under one line, its
   * synthesis alone in sight (2026-10-14: an intention's page). */
  folded?: { title: string; hint?: string };
  /** The way to analyse again, when its context moved on since (LEKA-441). */
  again?: React.ReactNode;
  /** The way on from what it proposes, under its proposals — apart from
   * what it found, as the proposals are: the one primary action. */
  next?: React.ReactNode;
  /** What its synthesis says, when more than its sentence (AnalysisSummary). */
  said?: React.ReactNode;
  onRetry?: () => void;
  /** Whether the proposals' section is drawn, even empty. */
  proposals?: boolean;
  /** Whether the synthesis heads it — not where the screen already says
   * it, as an incident's band; its confidence then heads the right side. */
  synthesis?: boolean;
  /** Its sections' headings' level. */
  level?: 2 | 3;
}) {
  const t = useDictionary();
  const w = t.intelligence;
  const evidence = evidenceOf(analysis);
  const explained = analysis.explanation ?? null;
  // "0 hypothèse(s)" beside a title says what its empty section already
  // says, and takes the room a side column does not have.
  const count = (said: string, n: number) =>
    n > 0 ? fill(said, { count: n }) : undefined;
  const details = (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,24rem)] xl:items-start">
      <div className="min-w-0 space-y-4">
        <IntelligenceSection
          kind="fact"
          title={w.findings.title}
          count={count(w.findings.count, analysis.findings.length)}
          level={level}
        >
          <FindingList findings={analysis.findings} max={4} />
        </IntelligenceSection>
        <IntelligenceSection
          kind="hypothesis"
          title={w.causes.title}
          count={count(w.causes.count, analysis.causes.length)}
          level={level}
        >
          <ProbableCauseList causes={analysis.causes} />
        </IntelligenceSection>
        <IntelligenceSection
          kind="evidence"
          title={w.evidence.title}
          count={count(w.evidence.count, evidence.length)}
          level={level}
        >
          <EvidenceList items={evidence} max={5} />
        </IntelligenceSection>
      </div>
      <div className="min-w-0 space-y-4">
        {explained ? (
          <>
            <NextStepPanel next={explained.next} level={level} />
            <ConfidenceExplained confidence={explained.confidence} level={level} />
          </>
        ) : synthesis ? null : (
          <ConfidencePanel
            score={analysis.confidence}
            support={analysis.support}
            level={level}
          />
        )}
        <IntelligenceSection
          kind="impact"
          title={w.impact.global}
          level={level}
        >
          <ImpactPanel impact={analysis.impact} />
        </IntelligenceSection>
        {proposals ? (
          <IntelligenceSection
            kind="proposal"
            title={w.recommendations.title}
            count={count(
              w.recommendations.count,
              analysis.recommendations.length,
            )}
            level={level}
          >
            <RecommendationList
              recommendations={analysis.recommendations}
              compact
              level={level === 2 ? 3 : 4}
            />
            {next ? <div className="mt-3">{next}</div> : null}
          </IntelligenceSection>
        ) : null}
        {explained ? (
          <>
            <ConflictList conflicts={explained.conflicts} level={level} />
            <AnalysisLimits explanation={explained} level={level} />
            <SourcesConsulted sources={explained.consulted} level={level} />
          </>
        ) : null}
        <UncertaintyList items={analysis.uncertainties} />
      </div>
    </div>
  );
  return (
    <div
      className="space-y-4"
      data-testid="analysis"
      data-status={analysis.status}
    >
      {explained?.freshness ? (
        <FreshnessNotice
          read={explained.freshness.read}
          now={explained.freshness.now}
          action={again}
        />
      ) : null}
      {explained?.understood ? <UnderstoodLine text={explained.understood} /> : null}
      <AnalysisState
        status={analysis.status}
        missing={analysis.missing}
        onRetry={onRetry}
      />
      {analysis.status === "failed" || analysis.status === "pending" ? (
        explained ? (
          // What stopped it, and what to do: never a bare « failed ».
          <div className="grid gap-4 xl:grid-cols-2">
            <NextStepPanel next={explained.next} level={level} />
            <AnalysisLimits explanation={explained} level={level} />
          </div>
        ) : null
      ) : (
        <>
          {synthesis ? (
            <AnalysisSummary analysis={analysis} level={level} said={said} />
          ) : null}
          {folded ? (
            <Folded title={folded.title} hint={folded.hint} testId="analysis-detail">
              {details}
            </Folded>
          ) : (
            details
          )}
        </>
      )}
    </div>
  );
}
