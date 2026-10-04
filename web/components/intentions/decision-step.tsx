"use client";

import { useState } from "react";

import { Form } from "@/components/forms/form";
import { ExampleNotice } from "@/components/intelligence/example";
import { RecommendationCard } from "@/components/intelligence/recommendations";
import { IntelligenceSection } from "@/components/intelligence/section";
import { useConfirm } from "@/components/interactions/confirm";
import {
  SELECTION_BAR_PADDING,
  SelectionActionBar,
} from "@/components/interactions/selection-action-bar";
import { Checkbox } from "@/components/ui/checkbox";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Recommendation } from "@/lib/intelligence";
import { notify } from "@/lib/notify";
import { z } from "@/lib/validation";

/**
 * The decision step: what LEKA proposes, chosen, approved or refused.
 *
 * Drawn with the intelligence components (LEKA-341): each recommendation a
 * proposal — why, what it would change, how risky, whether it can be
 * undone, how sure LEKA is — never a fact. Until the analysis engine
 * proposes its own (LEKA-384), the three below are an example, and the
 * screen says so before anything else.
 *
 * WHY THE TWO ACTIONS ASK DIFFERENTLY. Approving applies changes to systems
 * that are running, so it shows what it will affect and says it out loud.
 * Refusing changes nothing outside LEKA, so it only asks for the one thing
 * the next person will want: why.
 */

const EXAMPLES: Recommendation[] = [
  {
    id: "rollback-payment-api",
    title: "Revenir à payment-api v2.8.3",
    rationale: "La latence a commencé avec la version 2.8.4 ; la précédente tenait la charge.",
    effect: "3 services concernés",
    risk: "medium",
    reversible: true,
    confidence: 0.82,
    evidence: [],
  },
  {
    id: "scale-db-pool",
    title: "Augmenter le pool de connexions",
    rationale: "auth-service partage la base : ses connexions manquent à payment-api.",
    effect: "auth-service partage la base",
    risk: "low",
    reversible: true,
    confidence: 0.64,
    evidence: [],
  },
  {
    id: "alert-p99",
    title: "Ajouter une alerte sur le p99",
    rationale: "Le p99 est passé de 180 ms à 2,1 s sans alerte.",
    effect: "Aucun impact en production",
    risk: "low",
    reversible: true,
    confidence: 0.9,
    evidence: [],
  },
];

const schema = z.object({ selected: z.array(z.string()) });
type Values = z.infer<typeof schema>;

export function DecisionStep() {
  const t = useDictionary();
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
      title: t.decision.approveTitle,
      description: t.decision.approveBody,
      confirmLabel: t.decision.approve,
      destructive: true,
      impact: chosen.map((item) => item.effect ?? item.title),
    });
    if (!ok) return;
    notify.success({ title: t.decision.approved });
    setSettled("approved");
  }

  async function reject() {
    const reason = await confirm({
      title: t.decision.rejectTitle,
      description: t.decision.rejectBody,
      confirmLabel: t.decision.reject,
      reasonLabel: t.decision.rejectReason,
    });
    // null means they backed out. An empty string means they went ahead
    // without saying why, which is allowed.
    if (reason === null) return;
    notify.info({ title: t.decision.rejected, description: reason || undefined });
    setSettled("rejected");
  }

  if (settled !== null) {
    return (
      <p data-testid="decision-settled" className="text-sm text-shell-muted">
        {settled === "approved" ? t.decision.approved : t.decision.rejected}
      </p>
    );
  }

  return (
    <Form form={form}>
      <div className={SELECTION_BAR_PADDING}>
        <IntelligenceSection kind="proposal" title={t.decision.title} level={2}>
          <div className="space-y-2">
            <ExampleNotice />
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
      </div>

      <SelectionActionBar
        count={selected.length}
        onClear={() => form.setValue("selected", [])}
        secondary={{ label: t.decision.reject, onClick: () => void reject() }}
        primary={{ label: t.decision.approve, onClick: () => void approve() }}
      />
    </Form>
  );
}
