"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { agentRunKeys } from "@/lib/agent-runs-queries";
import { ApiError } from "@/lib/api";
import {
  type AgentLaunch,
  type IntentionAnalysisRead,
  type IntentionAnswer,
  type IntentionDetail,
  type IntentionFilters,
  type IntentionPhase,
  intentions,
} from "@/lib/intentions/api";
import { working } from "@/lib/intentions/journey";

export const intentionKeys = {
  all: ["intentions"] as const,
  list: (phase: IntentionPhase | null, q: string, filters: IntentionFilters = {}) =>
    ["intentions", "list", phase, q, filters] as const,
  counts: ["intentions", "counts"] as const,
  one: (id: string) => ["intentions", "one", id] as const,
  history: (id: string) => ["intentions", "history", id] as const,
  analysis: (id: string) => ["intentions", "analysis", id] as const,
  analyses: (id: string) => ["intentions", "analyses", id] as const,
  routing: (id: string) => ["intentions", "routing", id] as const,
  feasibility: (id: string) => ["intentions", "feasibility", id] as const,
  offer: (id: string, agents?: readonly string[]) =>
    ["intentions", "offer", id, agents?.join(",") ?? null] as const,
};

/** How often an analysis on its way is read again. */
const WHILE_RUNNING = 4_000;

/** A list of them, a page at a time: by phase — none, every one not
 * archived — and words. */
export function useIntentions(
  phase: IntentionPhase | null,
  q: string,
  filters: IntentionFilters = {},
  limit = 20,
) {
  return useInfiniteQuery({
    queryKey: [...intentionKeys.list(phase, q, filters), limit],
    queryFn: ({ pageParam }) => intentions.list({ phase, q, filters, cursor: pageParam, limit }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    // A row LEKA works on moves by itself: read again, as its page is.
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.data.some((row) => working(row.journey)))
        ? WHILE_WORKING * 3
        : false,
  });
}

export function useIntentionCounts() {
  return useQuery({ queryKey: intentionKeys.counts, queryFn: intentions.counts });
}

/** How often what LEKA is working on is read again (LEKA-443): its state is
 * the API's, never a progress drawn here. */
const WHILE_WORKING = 5_000;

export function useIntention(id: string) {
  return useQuery({
    queryKey: intentionKeys.one(id),
    queryFn: () => intentions.one(id),
    enabled: Boolean(id),
    refetchInterval: (query) => (working(query.state.data?.journey) ? WHILE_WORKING : false),
  });
}

export function useIntentionHistory(id: string) {
  return useQuery({
    queryKey: intentionKeys.history(id),
    queryFn: () => intentions.history(id),
    enabled: Boolean(id),
  });
}

type Change = "cancel" | "archive" | "restore" | "stop";

/** Cancelling, archiving, restoring, stopping its analysis (LEKA-443): the
 * intention as it now is, and every list, count and analysis read again. */
export function useIntentionChange(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ change, reason }: { change: Change; reason?: string }) =>
      change === "cancel" ? intentions.cancel(id, reason) : intentions[change](id),
    onSuccess: (updated: IntentionDetail) => {
      client.setQueryData(intentionKeys.one(id), updated);
      void client.invalidateQueries({ queryKey: intentionKeys.all });
    },
  });
}

/** Its latest analysis (LEKA-388): none while there is none yet — read
 * again every few seconds while `live` says one is on its way. */
export function useIntentionAnalysis(
  id: string,
  live: (analysis: IntentionAnalysisRead | null | undefined) => boolean,
) {
  return useQuery({
    queryKey: intentionKeys.analysis(id),
    queryFn: async () => {
      try {
        return await intentions.analysis(id);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: Boolean(id),
    refetchInterval: (query) => (live(query.state.data) ? WHILE_RUNNING : false),
  });
}

export function useIntentionAnalyses(id: string) {
  return useQuery({
    queryKey: intentionKeys.analyses(id),
    queryFn: () => intentions.analyses(id),
    enabled: Boolean(id),
  });
}

/** Analysed again: queued; the intention, its analyses and lists read
 * again. */
export function useAnalyseAgain(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => intentions.analyse(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: intentionKeys.all });
    },
  });
}

/** Where it was routed, and why (LEKA-398). */
export function useIntentionRouting(id: string) {
  return useQuery({
    queryKey: intentionKeys.routing(id),
    queryFn: () => intentions.routing(id),
    enabled: Boolean(id),
  });
}

/** Routed again: the decision read anew. */
export function useRouteAgain(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => intentions.route(id),
    onSuccess: (routing) => client.setQueryData(intentionKeys.routing(id), routing),
  });
}

/** What it takes to carry it through here (LEKA-439). */
export function useIntentionFeasibility(id: string, enabled = true) {
  return useQuery({
    queryKey: intentionKeys.feasibility(id),
    queryFn: () => intentions.feasibility(id),
    enabled: Boolean(id) && enabled,
  });
}

/** What carrying it through costs here (LEKA-458) — read again when the
 * agents chosen change, and while a payment is confirmed. */
export function useIntentionOffer(
  id: string,
  agents: readonly string[] | undefined,
  { enabled = true, following = false }: { enabled?: boolean; following?: boolean } = {},
) {
  return useQuery({
    queryKey: intentionKeys.offer(id, agents),
    queryFn: () => intentions.offer(id, agents),
    enabled: Boolean(id) && enabled,
    placeholderData: (previous) => previous,
    refetchInterval: following ? 3_000 : false,
  });
}

/** Its asker answers LEKA's questions (LEKA-439): asked again with them —
 * the intention, its history and what it takes, read again. */
export function useAnswer(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (answers: IntentionAnswer[]) => intentions.answer(id, answers),
    onSuccess: (asked) => {
      client.setQueryData(intentionKeys.one(id), asked.intention);
      void client.invalidateQueries({ queryKey: intentionKeys.history(id) });
      void client.invalidateQueries({ queryKey: intentionKeys.feasibility(id) });
      void client.invalidateQueries({ queryKey: intentionKeys.analysis(id) });
      void client.invalidateQueries({ queryKey: intentionKeys.counts });
    },
  });
}

/** The Décision step's two ways, and « Relancer » (2026-10-14): the
 * intention as it now stands, its agents read again. */
export function useDecide(id: string) {
  const client = useQueryClient();
  const settled = (updated: IntentionDetail) => {
    client.setQueryData(intentionKeys.one(id), updated);
    void client.invalidateQueries({ queryKey: intentionKeys.all });
    void client.invalidateQueries({ queryKey: agentRunKeys.intention(id) });
  };
  return {
    launch: useMutation({
      mutationFn: (agents: AgentLaunch[]) => intentions.launch(id, agents),
      onSuccess: settled,
    }),
    byHand: useMutation({ mutationFn: () => intentions.byHand(id), onSuccess: settled }),
    retry: useMutation({ mutationFn: () => intentions.retryAgents(id), onSuccess: settled }),
  };
}
