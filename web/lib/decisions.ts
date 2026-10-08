/**
 * People's decisions on what intentions ask to do (LEKA-390): the actions
 * proposed, how risky, how many must approve under the workspace's policy,
 * every vote kept — what À valider lists and the intention's page shows.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Decision = components["schemas"]["DecisionRead"];
export type DecisionVote = components["schemas"]["DecisionVoteRead"];
export type DecisionProposal = components["schemas"]["ProposalRead"];
export type DecisionItem = components["schemas"]["DecisionQueueItem"];
export type DecisionSummary = components["schemas"]["DecisionSummary"];
export type ApprovalPolicy = components["schemas"]["ApprovalPolicyRead"];
export type DecisionStatus = Decision["status"];
export type Risk = Decision["risk"];
/** À valider's states, as the API's queue names them. */
export type DecisionQueue = "proposed" | "approved" | "rejected" | "withdrawn";
export type VoteKind = "approve" | "reject" | "modify" | "request-changes";

export interface VoteBody {
  reason?: string | null;
  environment?: string | null;
  keep?: string[] | null;
}

export const decisions = {
  queue: (status: DecisionQueue) =>
    apiFetch<{ data: DecisionItem[] }>(`/decisions?status=${status}`),
  summary: () => apiFetch<DecisionSummary>("/decisions/summary"),
  policy: () => apiFetch<ApprovalPolicy>("/decisions/policy"),
  of: (intentionId: string) => apiFetch<Decision[]>(`/intentions/${intentionId}/decisions`),
  vote: (intentionId: string, kind: VoteKind, body: VoteBody) =>
    apiFetch<Decision>(`/intentions/${intentionId}/decision/${kind}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/** How many more approvals it needs on its current revision. */
export function remaining(decision: Decision): number {
  return Math.max(decision.required_approvals - decision.approvers.length, 0);
}

/** Whether this person may approve it: who may approve, not already one
 * of its approvers, and not its asker when the policy keeps them apart. */
export function mayApprove(decision: Decision, me: string | undefined, steward: boolean): boolean {
  if (!decision.open || !steward || !me) return false;
  if (decision.approvers.includes(me)) return false;
  return !(decision.separate_asker && decision.asked_by === me);
}
