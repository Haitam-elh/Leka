"use client";

import {
  AnalysisView,
  ConfidenceBadge,
  ConfidencePanel,
  ControlNotice,
  EvidenceList,
  EvidenceStrip,
  ExampleNotice,
  FindingList,
  ImpactPanel,
  IntelligenceSection,
  ProbableCauseList,
  RecommendationCard,
  RiskBadge,
} from "@/components/intelligence";
import { Checkbox } from "@/components/ui/checkbox";

import {
  COMPLETE,
  DEPLOYED,
  FAILED,
  INCONCLUSIVE,
  INFERRED,
  PARTIAL,
  PENDING,
  RECOMMENDATIONS,
  RECORD,
  RUNNING,
  SUPPORT,
} from "./fixtures";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4 rounded-xl border border-shell-line bg-white p-5">
      <h2 className="text-sm font-semibold tracking-wide text-shell-muted uppercase">{title}</h2>
      {children}
    </section>
  );
}

/**
 * Every intelligence component, and an analysis in each of its states
 * (LEKA-341), as mockups 03 to 05 draw them:
 * docs/frontend/intelligence-components.md says when to use which.
 */
export function IntelligenceGallery() {
  return (
    <main className="mx-auto max-w-6xl space-y-6 bg-shell-page p-6">
      <h1 className="text-xl font-semibold text-brand-navy">Composants d&apos;intelligence</h1>

      <Section title="Confiance et risque — en mots">
        <div className="flex flex-wrap gap-4">
          <ConfidenceBadge score={0.92} basis="stated" />
          <ConfidenceBadge score={0.7} basis="inferred" />
          <ConfidenceBadge score={0.3} />
          <ConfidenceBadge score={null} />
        </div>
        <div className="flex flex-wrap gap-2">
          <RiskBadge level="high" />
          <RiskBadge level="medium" />
          <RiskBadge level="low" />
          <RiskBadge level="unknown" />
        </div>
        <div className="max-w-sm">
          <ConfidencePanel score={0.83} support={SUPPORT} />
        </div>
      </Section>

      <Section title="Constats et causes — ce qui est su, ce qui est pensé">
        <FindingList findings={COMPLETE.findings} />
        <ProbableCauseList causes={COMPLETE.causes} />
      </Section>

      <Section title="Preuves — à ouvrir">
        <EvidenceList items={[RECORD, DEPLOYED, INFERRED]} max={2} />
        <EvidenceStrip
          title="Éléments qui justifient cette recommandation"
          items={[RECORD, DEPLOYED, INFERRED]}
          max={2}
        />
      </Section>

      <Section title="Impact">
        <div className="max-w-md">
          <IntelligenceSection kind="impact" title="Impact global">
            <ImpactPanel impact={COMPLETE.impact} />
          </IntelligenceSection>
        </div>
      </Section>

      <Section title="Recommandations — des propositions, pas des faits">
        <ExampleNotice body="Exemple de la galerie : aucune de ces recommandations n'est réelle." />
        {RECOMMENDATIONS.map((recommendation) => (
          <RecommendationCard
            key={recommendation.id}
            recommendation={recommendation}
            level={3}
            control={<Checkbox aria-label={recommendation.title} />}
          />
        ))}
        <ControlNotice />
      </Section>

      <Section title="Analyse complète">
        <AnalysisView analysis={COMPLETE} />
      </Section>
      <Section title="Analyse en cours">
        <AnalysisView analysis={RUNNING} />
      </Section>
      <Section title="Analyse partielle, sous un bandeau qui la résume déjà">
        <AnalysisView analysis={PARTIAL} synthesis={false} />
      </Section>
      <Section title="Analyse non concluante">
        <AnalysisView analysis={INCONCLUSIVE} />
      </Section>
      <Section title="Analyse en échec">
        <AnalysisView analysis={FAILED} onRetry={() => undefined} />
      </Section>
      <Section title="Pas encore d'analyse">
        <AnalysisView analysis={PENDING} />
      </Section>
    </main>
  );
}
