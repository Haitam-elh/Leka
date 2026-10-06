"use client";

/**
 * The counts the sidebar shows beside an entry.
 *
 * A count is shown when a feature reports a real one, and not before
 * (decided 2026-09-25: real data or an honest empty state, never the
 * mockup's figures — it used to be a mocked "3" beside À valider, for
 * every workspace).
 *
 * À valider: the enrichments LEKA proposes that wait for a decision
 * (LEKA-380), for who may decide — a member who cannot approve is not
 * shown the queue. The decisions on intentions (LEKA-390) add theirs.
 * The shell is handed numbers by key and never asks an API itself.
 */

import { usePermissions } from "@/components/shell/shell-provider";
import type { BadgeKey } from "@/config/routes";
import { useEnrichmentSummary } from "@/lib/enrichment-queries";

export function useNavBadges(): Partial<Record<BadgeKey, number>> {
  const mayApprove = usePermissions()?.includes("intention:approve") ?? false;
  const summary = useEnrichmentSummary(mayApprove);
  const waiting = mayApprove ? (summary.data?.proposed ?? 0) : 0;
  return waiting > 0 ? { approvals: waiting } : {};
}
