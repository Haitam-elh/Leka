"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { codeChanges } from "@/lib/code-changes";
import { LIVE_EVERY } from "@/lib/live";

export const codeChangeKeys = {
  all: ["code-changes"] as const,
  intention: (id: string) => ["code-changes", "intention", id] as const,
  run: (id: string) => ["code-changes", "run", id] as const,
};

/** An intention's proposed changes — read again every few seconds while
 * an agent may still be proposing one. */
export function useCodeChanges(intentionId: string, following: boolean) {
  return useQuery({
    queryKey: codeChangeKeys.intention(intentionId),
    queryFn: () => codeChanges.list(intentionId),
    enabled: Boolean(intentionId),
    refetchInterval: following ? 4000 : LIVE_EVERY,
  });
}

/** What one run proposed — read again while it is still to decide, and
 * while LEKA writes it (`writing`). */
export function useRunCodeChanges(runId: string | null, writing = false) {
  return useQuery({
    queryKey: codeChangeKeys.run(runId ?? ""),
    queryFn: () => codeChanges.forRun(runId ?? ""),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      writing || (query.state.data ?? []).some((change) => change.status === "proposed") ? 4000 : LIVE_EVERY,
  });
}

export const followKey = (id: string) => [...codeChangeKeys.all, "follow", id] as const;

/** Where its pull request stands, read on GitHub — again every minute
 * until deployed, closed or quiet (2026-10-20); every few seconds while
 * LEKA repairs it (2026-10-24). */
export function useCodeChangeFollow(id: string, following: boolean) {
  return useQuery({
    queryKey: followKey(id),
    queryFn: () => codeChanges.follow(id),
    enabled: following,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.repairs?.at(-1)?.state === "running") return 5000;
      return data?.follow?.done ? false : 60_000;
    },
  });
}

/** « Réparer le problème » (2026-10-24): asked, the change as the API says
 * it — its repair running — read again until it ends. */
export function useCodeChangeRepair(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => codeChanges.repair(id),
    onSuccess: (change) => client.setQueryData(followKey(id), change),
    onSettled: () => client.invalidateQueries({ queryKey: codeChangeKeys.all }),
  });
}

/** Undoing it, or going back to the version before it (2026-10-20): every
 * change read again after — the one that undoes it appears. */
export function useCodeChangeUndo() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: codeChangeKeys.all });
  return {
    undo: useMutation({ mutationFn: (id: string) => codeChanges.undo(id), onSettled: refresh }),
    rollback: useMutation({ mutationFn: (id: string) => codeChanges.rollback(id), onSettled: refresh }),
  };
}

export function useCodeChangeDecision() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: codeChangeKeys.all });
  return {
    accept: useMutation({
      mutationFn: ({ id, note }: { id: string; note?: string }) => codeChanges.accept(id, note),
      onSettled: refresh,
    }),
    reject: useMutation({
      mutationFn: ({ id, note }: { id: string; note?: string }) => codeChanges.reject(id, note),
      onSettled: refresh,
    }),
  };
}
