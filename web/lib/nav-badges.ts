"use client";

/**
 * The counts the sidebar shows beside an entry.
 *
 * A count is shown when a feature reports a real one, and not before
 * (decided 2026-09-25: real data or an honest empty state, never the
 * mockup's figures — it used to be a mocked "3" beside À valider, for
 * every workspace).
 *
 * À valider: the enrichments LEKA proposes (LEKA-380) and the conflicts
 * between sources (LEKA-382) that wait for a decision, for who may decide
 * — a member who cannot approve is not shown the queue — and the
 * decisions on what intentions ask to do (LEKA-390).
 * The shell is handed numbers by key and never asks an API itself.
 */

import { usePermissions } from "@/components/shell/shell-provider";
import type { BadgeKey } from "@/config/routes";
import { useConflictSummary } from "@/lib/conflicts-queries";
import { useDecisionSummary } from "@/lib/decisions-queries";
import { useEnrichmentSummary } from "@/lib/enrichment-queries";

export function useNavBadges(): Partial<Record<BadgeKey, number>> {
  const mayApprove = usePermissions()?.includes("intention:approve") ?? false;
  const proposals = useEnrichmentSummary(mayApprove);
  const conflicts = useConflictSummary(mayApprove);
  const decisions = useDecisionSummary(mayApprove);
  const waiting = mayApprove
    ? (proposals.data?.proposed ?? 0) +
      (conflicts.data?.open ?? 0) +
      (decisions.data?.proposed ?? 0)
    : 0;
  return waiting > 0 ? { approvals: waiting } : {};
}
