"use client";

import { useState } from "react";

import { Form } from "@/components/forms/form";
import {
  ConfidencePanel,
  ControlNotice,
  ExampleNotice,
  ImpactPanel,
  IntelligenceSection,
  RecommendationCard,
} from "@/components/intelligence";
import { useConfirm } from "@/components/interactions/confirm";
import {
  SELECTION_BAR_PADDING,
  SelectionActionBar,
} from "@/components/interactions/selection-action-bar";
import { Checkbox } from "@/components/ui/checkbox";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { EvidenceRef, Impact, Recommendation, Support } from "@/lib/intelligence";
import { notify } from "@/lib/notify";
import { z } from "@/lib/validation";

/**
 * The decision step: what LEKA proposes, chosen, approved or refused — laid
 * out as mockup 05. On the left the recommendations, a card each to tick —
 * why, its priority, what it touches, how long, whether it can be undone,
 * how sure LEKA is, the elements that justify it — then "Vous gardez le
 * contrôle"; on the right what they rest on: the impact, the confidence,
 * the next steps. Drawn with the intelligence components (LEKA-341).
 *
 * AN EXAMPLE, SAID FIRST. Until the analysis engine proposes its own
 * (LEKA-388, decisions LEKA-390), everything on this step is an example —
 * the recommendations, their impact, their confidence — and the screen
 * says so before anything else. None of it is read from the workspace.
 *
 * WHY THE TWO ACTIONS ASK DIFFERENTLY. Approving applies changes to systems
 * that are running, so it shows what it will affect and says it out loud.
 * Refusing changes nothing outside LEKA, so it only asks for the one thing
 * the next person will want: why.
 */

const DEPLOYED: EvidenceRef = {
  id: "example-deployed",
  label: "Déploiement payment-api v2.8.4",
  kind: "event",
  source: { kind: "github", name: "GitHub" },
  detail: "Exemple",
};

const LATENCY: EvidenceRef = {
  id: "example-latency",
  label: "Hausse de latence (p99)",
  kind: "record",
  source: { kind: "datadog", name: "Datadog" },
  detail: "Exemple",
};

const SHARED: EvidenceRef = {
  id: "example-shared",
  label: "auth-service partage la base",
  kind: "inference",
  detail: "Exemple",
};

const EXAMPLES: Recommendation[] = [
  {
    id: "rollback-payment-api",
    title: "Revenir à payment-api v2.8.3",
    rationale: "La latence a commencé avec la version 2.8.4 ; la précédente tenait la charge.",
    effect: "3 services concernés",
    effort: "≈ 15 min",
    action: "rollback",
    priority: "high",
    risk: "medium",
    reversible: true,
    confidence: 0.82,
    evidence: [DEPLOYED, LATENCY],
  },
  {
    id: "scale-db-pool",
    title: "Augmenter le pool de connexions",
    rationale: "auth-service partage la base : ses connexions manquent à payment-api.",
    effect: "auth-service partage la base",
    effort: "≈ 30 min",
    action: "change",
    priority: "medium",
    risk: "low",
    reversible: true,
    confidence: 0.64,
    evidence: [SHARED],
  },
  {
    id: "alert-p99",
    title: "Ajouter une alerte sur le p99",
    rationale: "Le p99 est passé de 180 ms à 2,1 s sans alerte.",
    effect: "Aucun impact en production",
    effort: "≈ 15 min",
    action: "monitor",
    priority: "low",
    risk: "low",
    reversible: true,
    confidence: 0.9,
    evidence: [LATENCY],
  },
];

const IMPACT: Impact = {
  areas: [
    {
      id: "affected",
      label: "Touché",
      items: [{ id: "payment-api", label: "payment-api", type: "service", detail: "Service" }],
    },
    {
      id: "dependents",
      label: "Qui en dépend",
      items: [
        { id: "checkout", label: "checkout", type: "service", detail: "Service" },
        { id: "auth-service", label: "auth-service", type: "service", detail: "Service" },
      ],
    },
  ],
  risk: "high",
  riskBasis: "Exemple",
};

const SUPPORT: Support[] = [
  { id: "sources", label: "3 sources lues", established: true },
  { id: "before", label: "1 déploiement juste avant", established: true },
  { id: "more", label: "D'autres sources pourraient affiner l'analyse", established: false },
];

const schema = z.object({ selected: z.array(z.string()) });
type Values = z.infer<typeof schema>;

export function DecisionStep() {
  const t = useDictionary();
  const w = t.decision;
  const confirm = useConfirm();
  const [settled, setSettled] = useState<string | null>(null);

  const form = useLekaForm<Values>({
    schema,
    defaultValues: { selected: [] },
    onSubmit: () => {},
  });

  const selected = form.watch("selected");

  function toggle(id: string, on: boolean) {
    const others = selected.filter((value) => value !== id);
    form.setValue("selected", on ? [...others, id] : others);
  }

  async function approve() {
    const chosen = EXAMPLES.filter((item) => selected.includes(item.id));
    const ok = await confirm({
      title: w.approveTitle,
      description: w.approveBody,
      confirmLabel: w.approve,
      destructive: true,
      impact: chosen.map((item) => item.effect ?? item.title),
    });
    if (!ok) return;
    notify.success({ title: w.approved });
    setSettled("approved");
  }

  async function reject() {
    const reason = await confirm({
      title: w.rejectTitle,
      description: w.rejectBody,
      confirmLabel: w.reject,
      reasonLabel: w.rejectReason,
    });
    // null means they backed out. An empty string means they went ahead
    // without saying why, which is allowed.
    if (reason === null) return;
    notify.info({ title: w.rejected, description: reason || undefined });
    setSettled("rejected");
  }

  if (settled !== null) {
    return (
      <p data-testid="decision-settled" className="text-sm text-shell-muted">
        {settled === "approved" ? w.approved : w.rejected}
      </p>
    );
  }

  return (
    <Form form={form}>
      <div className={SELECTION_BAR_PADDING}>
        <ExampleNotice body={w.example} />
        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] xl:items-start">
          <div className="min-w-0 space-y-4">
            <IntelligenceSection
              kind="proposal"
              title={w.title}
              subtitle={t.intelligence.recommendations.select}
              count={fill(t.intelligence.recommendations.count, { count: EXAMPLES.length })}
              level={2}
            >
              <div className="space-y-3">
                {EXAMPLES.map((item) => (
                  <RecommendationCard
                    key={item.id}
                    recommendation={item}
                    level={3}
                    selected={selected.includes(item.id)}
                    control={
                      <Checkbox
                        checked={selected.includes(item.id)}
                        onCheckedChange={(checked) => toggle(item.id, checked === true)}
                        aria-label={item.title}
                      />
                    }
                  />
                ))}
              </div>
            </IntelligenceSection>
            <ControlNotice />
          </div>

          <aside aria-label={w.aside} className="min-w-0 space-y-4">
            <IntelligenceSection kind="impact" title={t.intelligence.impact.global} level={2}>
              <ImpactPanel impact={IMPACT} />
            </IntelligenceSection>
            <ConfidencePanel score={0.82} support={SUPPORT} level={2} />
            <NextSteps />
          </aside>
        </div>
      </div>

      <SelectionActionBar
        className="max-w-none"
        count={selected.length}
        onClear={() => form.setValue("selected", [])}
        secondary={{ label: w.reject, onClick: () => void reject() }}
        primary={{ label: w.approve, onClick: () => void approve() }}
      />
    </Form>
  );
}

/** Mockup 05's "Prochaines étapes": what follows a yes — the process, not
 * data. */
function NextSteps() {
  const t = useDictionary();
  const w = t.decision.next;
  const steps = [
    { label: w.validate, when: w.now },
    { label: w.plan, when: null },
    { label: w.follow, when: null },
  ];
  return (
    <section
      aria-labelledby="decision-next"
      className="rounded-xl border border-shell-line bg-white p-4"
    >
      <h2
        id="decision-next"
        className="mb-3 text-[1.0625rem] font-semibold tracking-[-0.01em] text-brand-navy"
      >
        {w.title}
      </h2>
      <ol className="space-y-2.5 text-[0.8125rem]">
        {steps.map((step, index) => (
          <li key={step.label} className="flex items-center gap-3">
            <span
              aria-hidden="true"
              className="flex size-6 shrink-0 items-center justify-center rounded-full bg-shell-canvas text-xs font-semibold text-brand-navy"
            >
              {index + 1}
            </span>
            <span className="flex-1 text-brand-navy">{step.label}</span>
            {step.when ? <span className="text-xs text-shell-muted">{step.when}</span> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
