"use client";

import { Gavel } from "lucide-react";

import { DecisionCard } from "@/components/decisions/decision-card";
import { Card } from "@/components/environment/parts";
import { useDecisionsOf } from "@/lib/decisions-queries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * An intention's latest decision on its page (LEKA-390): waiting, who may
 * decide does it here; decided, what was decided and by whom. Nothing when
 * it asks to change nothing.
 */
export function IntentionDecision({ intentionId }: { intentionId: string }) {
  const t = useDictionary();
  const found = useDecisionsOf(intentionId);
  const latest = found.data?.[0];
  if (!latest) return null;
  return (
    <Card
      title={t.decisions.title}
      icon={<Gavel className="size-4 text-shell-muted" aria-hidden="true" />}
    >
      <DecisionCard decision={latest} />
    </Card>
  );
}
