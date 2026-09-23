"use client";

import { useState } from "react";

import { Form } from "@/components/forms/form";
import { SelectableListField } from "@/components/forms/selectable-list-field";
import { useConfirm } from "@/components/interactions/confirm";
import {
  SELECTION_BAR_PADDING,
  SelectionActionBar,
} from "@/components/interactions/selection-action-bar";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { z } from "@/lib/validation";

/**
 * The decision step, reduced to the interaction it exists to prove.
 *
 * Deliberately a skeleton. What a recommendation looks like — the evidence
 * behind it, the diff it would apply, the confidence — is LEKA-341's, and
 * building a rich card here would mean building it twice. What is real is
 * the pattern: pick from a list, act on the selection, and be asked before
 * anything touches a customer's infrastructure.
 *
 * WHY THE TWO ACTIONS ASK DIFFERENTLY. Approving applies changes to systems
 * that are running, so it shows what it will affect and says it out loud.
 * Refusing changes nothing outside LEKA, so it only asks for the one thing
 * the next person will want: why.
 *
 * TODO LEKA-341: real recommendations, from the analysis.
 */

const RECOMMENDATIONS = [
  {
    value: "rollback-payment-api",
    title: "Revenir à payment-api v2.8.3",
    subtitle: "Rollback disponible · 3 services concernés",
  },
  {
    value: "scale-db-pool",
    title: "Augmenter le pool de connexions",
    subtitle: "auth-service partage la base",
  },
  {
    value: "alert-p99",
    title: "Ajouter une alerte sur le p99",
    subtitle: "Aucun impact en production",
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

  async function approve() {
    const chosen = RECOMMENDATIONS.filter((item) => selected.includes(item.value));
    const ok = await confirm({
      title: t.decision.approveTitle,
      description: t.decision.approveBody,
      confirmLabel: t.decision.approve,
      destructive: true,
      impact: chosen.map((item) => item.subtitle),
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
        <SelectableListField<Values, "selected">
          name="selected"
          label={t.decision.title}
          items={RECOMMENDATIONS}
        />
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
