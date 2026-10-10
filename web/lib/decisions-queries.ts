"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type ApprovalPolicyUpdate,
  type DecisionQueue,
  type DelegationCreate,
  decisions,
  type GovernanceExceptionCreate,
  type PolicyProbe,
  type VoteBody,
  type VoteKind,
} from "@/lib/decisions";
import { intentionKeys } from "@/lib/intentions/queries";

export const decisionKeys = {
  all: ["decisions"] as const,
  summary: ["decisions", "summary"] as const,
  policy: ["decisions", "policy"] as const,
  exceptions: ["decisions", "exceptions"] as const,
  delegations: ["decisions", "delegations"] as const,
  history: ["decisions", "governance-history"] as const,
  queue: (status: DecisionQueue) => ["decisions", "queue", status] as const,
  of: (intentionId: string) => ["decisions", "of", intentionId] as const,
};

export function useDecisionSummary(enabled = true) {
  return useQuery({ queryKey: decisionKeys.summary, queryFn: decisions.summary, enabled });
}

export function useDecisionQueue(status: DecisionQueue) {
  return useQuery({ queryKey: decisionKeys.queue(status), queryFn: () => decisions.queue(status) });
}

export function useApprovalPolicy() {
  return useQuery({ queryKey: decisionKeys.policy, queryFn: decisions.policy });
}

/** Every decision on an intention, the latest first. */
export function useDecisionsOf(intentionId: string) {
  return useQuery({
    queryKey: decisionKeys.of(intentionId),
    queryFn: () => decisions.of(intentionId),
    enabled: Boolean(intentionId),
  });
}

/** Who lent their authority to approve, to whom (LEKA-404). */
export function useDelegations(enabled = true) {
  return useQuery({ queryKey: decisionKeys.delegations, queryFn: decisions.delegations, enabled });
}

export function useGovernanceExceptions() {
  return useQuery({ queryKey: decisionKeys.exceptions, queryFn: decisions.exceptions });
}

export function useGovernanceHistory() {
  return useQuery({ queryKey: decisionKeys.history, queryFn: decisions.history });
}

/** Every change of governance invalidates what it touches, the trail too. */
function useGovernanceChange<T, R>(change: (input: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: change,
    onSuccess: () => void client.invalidateQueries({ queryKey: decisionKeys.all }),
  });
}

export function useSetPolicy() {
  return useGovernanceChange((change: ApprovalPolicyUpdate) => decisions.setPolicy(change));
}

export function useEvaluatePolicy() {
  return useMutation({ mutationFn: (probe: PolicyProbe) => decisions.evaluate(probe) });
}

export function useGrantException() {
  return useGovernanceChange((body: GovernanceExceptionCreate) => decisions.grantException(body));
}

export function useRevokeException() {
  return useGovernanceChange((id: string) => decisions.revokeException(id));
}

export function useDelegate() {
  return useGovernanceChange((body: DelegationCreate) => decisions.delegate(body));
}

export function useRevokeDelegation() {
  return useGovernanceChange((id: string) => decisions.revokeDelegation(id));
}

/** A vote: the decisions, the intention it moved and the lists read again. */
export function useVote(intentionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, body }: { kind: VoteKind; body: VoteBody }) =>
      decisions.vote(intentionId, kind, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: decisionKeys.all });
      void client.invalidateQueries({ queryKey: intentionKeys.all });
    },
  });
}
