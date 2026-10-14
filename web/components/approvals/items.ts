/**
 * What waits in À valider, as one list: the enrichments LEKA proposes
 * (LEKA-380), the conflicts between sources (LEKA-382) and the decisions on
 * what intentions ask to do (LEKA-390) — each worded, in one of the queue's
 * four states.
 */

import { levelWord, wordCandidate } from "@/components/approvals/words";
import { actionWord } from "@/components/decisions/decision-card";
import type { Conflict, ConflictStatus } from "@/lib/conflicts";
import type { DecisionItem, DecisionQueue } from "@/lib/decisions";
import type { Candidate, CandidateStatus } from "@/lib/enrichment";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";

/** The queue's states, named as a proposal's: a conflict open waits, settled
 * is decided, dismissed is refused, no longer disputed is withdrawn. */
export const CONFLICT_STATUS: Record<CandidateStatus, ConflictStatus> = {
  proposed: "open",
  accepted: "resolved",
  rejected: "dismissed",
  withdrawn: "gone",
};

/** The queue's states, named as a decision's queue: approved is decided,
 * superseded or sent back is withdrawn. */
export const DECISION_STATUS: Record<CandidateStatus, DecisionQueue> = {
  proposed: "proposed",
  accepted: "approved",
  rejected: "rejected",
  withdrawn: "withdrawn",
};

export type Item =
  | { kind: "candidate"; id: string; family: string; data: Candidate }
  | { kind: "conflict"; id: string; family: "conflict"; data: Conflict }
  | { kind: "decision"; id: string; family: "action"; data: DecisionItem };

export interface Worded {
  title: string;
  why: string | null;
}

export function items(
  candidates: Candidate[],
  conflicts: Conflict[],
  decisions: DecisionItem[] = [],
): Item[] {
  return [
    ...decisions.map((data) => ({
      kind: "decision" as const,
      id: data.decision.id,
      family: "action" as const,
      data,
    })),
    ...conflicts.map((data) => ({ kind: "conflict" as const, id: data.id, family: "conflict" as const, data })),
    ...candidates.map((data) => ({ kind: "candidate" as const, id: data.id, family: data.family, data })),
  ];
}

/** "Redémarrer Billing API · production" — and what it needs. */
export function wordDecision(t: Dictionary, item: DecisionItem): Worded {
  const { decision } = item;
  const [first] = decision.proposals;
  const actions = decision.proposals.map((p) => actionWord(t, p.action)).join(", ");
  const targets = first ? first.targets.map((target) => target.name).join(", ") : "";
  const where = first?.environment ? ` · ${first.environment}` : "";
  return {
    title: `${actions} ${targets}${where}`.trim(),
    why: [
      t.decisions.risks[decision.risk],
      fill(t.decisions.required, { count: decision.required_approvals }),
    ].join(" · "),
  };
}

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" || typeof value === "number" ? String(value) : JSON.stringify(value);
}

/** A side's value as the reader reads it: a criticality in their words. */
export function sideWord(t: Dictionary, conflict: Conflict, value: unknown): string {
  return conflict.about === "criticality" ? levelWord(t, value) : text(value);
}

export function aboutWord(t: Dictionary, about: string): string {
  return (t.approvals.conflict.abouts as Record<string, string>)[about] ?? about;
}

/** "SLA de payment-api : 99.95 ou 99.9" — and what LEKA recommends. */
export function wordConflict(t: Dictionary, conflict: Conflict): Worded {
  const c = t.approvals.conflict;
  const values = conflict.sides.map((side) => sideWord(t, conflict, side.value));
  const title = fill(c.title, {
    about: aboutWord(t, conflict.about),
    name: conflict.subject.name,
    values: values.join(c.or),
  });
  const index = conflict.recommendation.side;
  if (index === null || index === undefined || !conflict.sides[index]) {
    return { title, why: c.noRecommendation };
  }
  const strength = (c.strength as Record<string, string>)[conflict.recommendation.strength] ?? "";
  return {
    title,
    why: [fill(c.recommends, { value: values[index] }), strength].filter(Boolean).join(" · "),
  };
}

/** How sure LEKA is, in words a customer reads (2026-10-14: « tout est à
 * 60 % »): a percentage said nothing about what to do with it. */
export function sureWord(t: Dictionary, confidence: number): string {
  const sure = t.approvals.sure;
  if (confidence >= 0.85) return sure.high;
  return confidence >= 0.7 ? sure.medium : sure.low;
}

export function wordItem(t: Dictionary, item: Item): Worded {
  if (item.kind === "decision") return wordDecision(t, item.data);
  return item.kind === "conflict" ? wordConflict(t, item.data) : wordCandidate(t, item.data);
}

/** When it last changed: decided, or seen. */
export function dateOf(item: Item): string {
  if (item.kind === "decision") return item.data.decision.decided_at ?? item.data.decision.created_at;
  if (item.kind === "candidate") return item.data.decided_at ?? item.data.last_seen_at;
  const at = item.data.resolution?.at;
  return typeof at === "string" ? at : item.data.last_seen_at;
}
