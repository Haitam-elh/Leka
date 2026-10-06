"use client";

import { Briefcase, type LucideIcon, Network, Sparkles, UsersRound } from "lucide-react";

import { cn } from "cn";
import type { Candidate, CandidateStatus } from "@/lib/enrichment";
import { useDictionary } from "@/lib/i18n/locale-provider";

/** Each family of proposal, its icon (LEKA-380). */
export const FAMILY_ICON: Record<string, LucideIcon> = {
  relationship: Network,
  organisation: UsersRound,
  business: Briefcase,
  semantic: Sparkles,
};

const BADGE: Record<CandidateStatus, string> = {
  proposed: "bg-state-warning-soft text-state-warning",
  accepted: "bg-state-success-soft text-state-success",
  rejected: "bg-state-danger-soft text-state-danger",
  withdrawn: "bg-shell-canvas text-shell-muted",
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
