"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { activity, type PeriodDays } from "@/lib/activity";
import { evolution } from "@/lib/evolution";

export const evolutionKeys = {
  all: ["evolution"] as const,
  history: (id: string) => ["evolution", "history", id] as const,
  at: (id: string, moment: string) => ["evolution", "at", id, moment] as const,
  activity: (days: PeriodDays) => ["evolution", "activity", days] as const,
  trends: ["evolution", "trends"] as const,
};

export function useEntityHistory(id: string) {
  return useQuery({ queryKey: evolutionKeys.history(id), queryFn: () => evolution.history(id) });
}

export function useEntityAt(id: string, moment: string | null) {
  return useQuery({
    queryKey: evolutionKeys.at(id, moment ?? ""),
    queryFn: () => evolution.at(id, moment ?? ""),
    enabled: moment !== null,
  });
}

export function useActivity(days: PeriodDays) {
  return useQuery({ queryKey: evolutionKeys.activity(days), queryFn: () => activity.read(days) });
}

export function useTrends() {
  return useQuery({ queryKey: evolutionKeys.trends, queryFn: activity.trends });
}

/** Restore a version, undo a restore, rebuild the model — each refreshing
 * the histories and Activité, where the operation is said. */
export function useOperations() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: evolutionKeys.all });
  return {
    restore: useMutation({
      mutationFn: ({ id, version, reason }: { id: string; version: number; reason?: string }) =>
        evolution.restore(id, { version, reason: reason || null }),
      onSuccess: refresh,
    }),
    undo: useMutation({
      mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
        evolution.undo(id, { reason: reason || null }),
      onSuccess: refresh,
    }),
    rebuild: useMutation({
      mutationFn: ({ reason }: { reason?: string }) => evolution.rebuild({ reason: reason || null }),
      onSuccess: refresh,
    }),
  };
}
