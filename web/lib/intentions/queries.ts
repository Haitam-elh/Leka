"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type IntentionDetail, type IntentionPhase, intentions } from "@/lib/intentions/api";

export const intentionKeys = {
  all: ["intentions"] as const,
  list: (phase: IntentionPhase | null, q: string) => ["intentions", "list", phase, q] as const,
  counts: ["intentions", "counts"] as const,
  one: (id: string) => ["intentions", "one", id] as const,
  history: (id: string) => ["intentions", "history", id] as const,
};

/** A list of them, a page at a time: by phase — none, every one not
 * archived — and words. */
export function useIntentions(phase: IntentionPhase | null, q: string) {
  return useInfiniteQuery({
    queryKey: intentionKeys.list(phase, q),
    queryFn: ({ pageParam }) => intentions.list({ phase, q, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
}

export function useIntentionCounts() {
  return useQuery({ queryKey: intentionKeys.counts, queryFn: intentions.counts });
}

export function useIntention(id: string) {
  return useQuery({
    queryKey: intentionKeys.one(id),
    queryFn: () => intentions.one(id),
    enabled: Boolean(id),
  });
}

export function useIntentionHistory(id: string) {
  return useQuery({
    queryKey: intentionKeys.history(id),
    queryFn: () => intentions.history(id),
    enabled: Boolean(id),
  });
}

type Change = "cancel" | "archive" | "restore";

/** Cancelling, archiving, restoring: the intention as it now is, and every
 * list and count read again. */
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
