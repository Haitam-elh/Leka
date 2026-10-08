"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type DecisionQueue, decisions, type VoteBody, type VoteKind } from "@/lib/decisions";
import { intentionKeys } from "@/lib/intentions/queries";

export const decisionKeys = {
  all: ["decisions"] as const,
  summary: ["decisions", "summary"] as const,
  policy: ["decisions", "policy"] as const,
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
