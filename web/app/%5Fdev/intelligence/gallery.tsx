"use client";

import {
  AnalysisView,
  ConfidenceBadge,
  EvidenceList,
  ExampleNotice,
  RecommendationCard,
  RiskBadge,
} from "@/components/intelligence";

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
 * (LEKA-341): docs/frontend/intelligence-components.md says when to use
 * which.
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
      </Section>

      <Section title="Preuves — à ouvrir">
        <EvidenceList items={[RECORD, DEPLOYED, INFERRED]} />
      </Section>

      <Section title="Recommandations — des propositions, pas des faits">
        <ExampleNotice body="Exemple de la galerie : aucune de ces recommandations n'est réelle." />
        {RECOMMENDATIONS.map((recommendation) => (
          <RecommendationCard
            key={recommendation.id}
            recommendation={recommendation}
            level={3}
          />
        ))}
      </Section>

      <Section title="Analyse complète">
        <AnalysisView analysis={COMPLETE} />
      </Section>
      <Section title="Analyse partielle">
        <AnalysisView analysis={PARTIAL} />
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
