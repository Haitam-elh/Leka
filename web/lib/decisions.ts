/**
 * People's decisions on what intentions ask to do (LEKA-390): the actions
 * proposed, how risky, how many must approve under the workspace's policy,
 * every vote kept — what À valider lists and the intention's page shows —
 * and their governance (LEKA-404): the policy's rules and requirements per
 * risk, freezes and waivers, approvals lent by delegation, the trail.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Decision = components["schemas"]["DecisionRead"];
export type DecisionVote = components["schemas"]["DecisionVoteRead"];
export type DecisionProposal = components["schemas"]["ProposalRead"];
export type DecisionItem = components["schemas"]["DecisionQueueItem"];
export type DecisionSummary = components["schemas"]["DecisionSummary"];
export type DecisionGovernance = components["schemas"]["DecisionGovernanceRead"];
export type ApprovalPolicy = components["schemas"]["ApprovalPolicyRead"];
export type ApprovalPolicyUpdate = components["schemas"]["ApprovalPolicyUpdate"];
export type RiskRule = components["schemas"]["RiskRuleRead"];
export type PolicyProbe = components["schemas"]["PolicyProbe"];
export type PolicyVerdict = components["schemas"]["PolicyVerdictRead"];
export type GovernanceException = components["schemas"]["GovernanceExceptionRead"];
export type GovernanceExceptionCreate = components["schemas"]["GovernanceExceptionCreate"];
export type Delegation = components["schemas"]["DelegationRead"];
export type DelegationCreate = components["schemas"]["DelegationCreate"];
export type DecisionGovernanceEvent = components["schemas"]["DecisionGovernanceEventRead"];
export type DecisionStatus = Decision["status"];
export type Risk = Decision["risk"];
/** À valider's states, as the API's queue names them. */
export type DecisionQueue = "proposed" | "approved" | "rejected" | "withdrawn";
export type VoteKind = "approve" | "reject" | "modify" | "request-changes";

/** The four levels, the least first. */
export const RISKS: readonly Risk[] = ["low", "medium", "high", "critical"];
export const RISK_RANK: Record<Risk, number> = { low: 1, medium: 2, high: 3, critical: 4 };

export interface VoteBody {
  reason?: string | null;
  environment?: string | null;
  keep?: string[] | null;
  /** Cast with this approver's authority, which they lent (LEKA-404). */
  on_behalf_of?: string | null;
}

export const decisions = {
  queue: (status: DecisionQueue) =>
    apiFetch<{ data: DecisionItem[] }>(`/decisions?status=${status}`),
  summary: () => apiFetch<DecisionSummary>("/decisions/summary"),
  policy: () => apiFetch<ApprovalPolicy>("/decisions/policy"),
  setPolicy: (change: ApprovalPolicyUpdate) =>
    apiFetch<ApprovalPolicy>("/decisions/policy", { method: "PUT", body: JSON.stringify(change) }),
  evaluate: (probe: PolicyProbe) =>
    apiFetch<PolicyVerdict>("/decisions/policy/evaluate", {
      method: "POST",
      body: JSON.stringify(probe),
    }),
  exceptions: () => apiFetch<GovernanceException[]>("/decisions/exceptions"),
  grantException: (body: GovernanceExceptionCreate) =>
    apiFetch<GovernanceException>("/decisions/exceptions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  revokeException: (id: string) =>
    apiFetch<GovernanceException>(`/decisions/exceptions/${id}/revoke`, { method: "POST" }),
  delegations: () => apiFetch<Delegation[]>("/decisions/delegations"),
  delegate: (body: DelegationCreate) =>
    apiFetch<Delegation>("/decisions/delegations", { method: "POST", body: JSON.stringify(body) }),
  revokeDelegation: (id: string) =>
    apiFetch<Delegation>(`/decisions/delegations/${id}/revoke`, { method: "POST" }),
  history: () => apiFetch<DecisionGovernanceEvent[]>("/decisions/governance-history"),
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

/** Whether an approval with this authority — the person's own, or one lent
 * to them (`authority`) — may be given: someone who may approve, that
 * authority not already among its approvers, neither the voter nor the
 * authority its asker when the policy keeps them apart. */
export function mayApprove(
  decision: Decision,
  me: string | undefined,
  steward: boolean,
  authority?: string | null,
): boolean {
  const whose = authority ?? me;
  if (!decision.open || !me || !whose || (!steward && !authority)) return false;
  if (decision.approvers.includes(whose)) return false;
  return !(decision.separate_asker && (decision.asked_by === me || decision.asked_by === whose));
}

/** The delegations lent to this person that hold now, at this risk: whose
 * authority they may vote with. */
export function lentTo(
  delegations: readonly Delegation[] | undefined,
  me: string | undefined,
  risk: Risk,
  now: Date = new Date(),
): Delegation[] {
  if (!me || !delegations) return [];
  return delegations.filter(
    (d) =>
      d.delegated_to === me &&
      d.revoked_at === null &&
      new Date(d.starts_at) <= now &&
      now < new Date(d.ends_at) &&
      RISK_RANK[risk] <= RISK_RANK[d.max_risk],
  );
}

/** Where an exception or a delegation stands now. */
export function windowState(
  item: { starts_at: string; ends_at: string; revoked_at: string | null },
  now: Date = new Date(),
): "active" | "upcoming" | "ended" | "revoked" {
  if (item.revoked_at) return "revoked";
  if (now < new Date(item.starts_at)) return "upcoming";
  return now < new Date(item.ends_at) ? "active" : "ended";
}
