"use client";

import { Briefcase, type LucideIcon, Network, Scale, Sparkles, UsersRound, Zap } from "lucide-react";

import { cn } from "cn";
import type { Item } from "@/components/approvals/items";
import { DecisionStatusPill } from "@/components/decisions/decision-card";
import type { Conflict, ConflictStatus } from "@/lib/conflicts";
import type { Candidate, CandidateStatus } from "@/lib/enrichment";
import { useDictionary } from "@/lib/i18n/locale-provider";

/** Each family of proposal, its icon (LEKA-380) — and a conflict's
 * (LEKA-382). */
export const FAMILY_ICON: Record<string, LucideIcon> = {
  relationship: Network,
  organisation: UsersRound,
  business: Briefcase,
  semantic: Sparkles,
  conflict: Scale,
  action: Zap,
};

const BADGE: Record<CandidateStatus, string> = {
  proposed: "bg-state-warning-soft text-state-warning",
  accepted: "bg-state-success-soft text-state-success",
  rejected: "bg-state-danger-soft text-state-danger",
  withdrawn: "bg-shell-canvas text-shell-muted",
};

const CONFLICT_BADGE: Record<ConflictStatus, string> = {
  open: BADGE.proposed,
  resolved: BADGE.accepted,
  dismissed: "bg-shell-canvas text-brand-navy",
  gone: BADGE.withdrawn,
};

export function CandidateBadge({ candidate }: { candidate: Candidate }) {
  const t = useDictionary();
  const label =
    candidate.status === "accepted" && candidate.decided_via === "policy"
      ? t.approvals.policy
      : t.approvals.status[candidate.status];
  return (
    <span
      className={cn("rounded-md px-2 py-0.5 text-xs font-medium", BADGE[candidate.status])}
      data-testid="candidate-status"
    >
      {label}
    </span>
  );
}

export function ConflictBadge({ conflict }: { conflict: Conflict }) {
  const t = useDictionary();
  return (
    <span
      className={cn("rounded-md px-2 py-0.5 text-xs font-medium", CONFLICT_BADGE[conflict.status])}
      data-testid="conflict-status"
    >
      {t.approvals.conflict.status[conflict.status]}
    </span>
  );
}

export function ItemBadge({ item }: { item: Item }) {
  if (item.kind === "decision") return <DecisionStatusPill decision={item.data.decision} />;
  return item.kind === "conflict" ? (
    <ConflictBadge conflict={item.data} />
  ) : (
    <CandidateBadge candidate={item.data} />
  );
}
