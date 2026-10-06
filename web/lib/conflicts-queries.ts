"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type ConflictStatus, conflicts } from "@/lib/conflicts";

export const conflictKeys = {
  all: ["conflicts"] as const,
  summary: ["conflicts", "summary"] as const,
  list: (status: ConflictStatus) => ["conflicts", "list", status] as const,
  detail: (id: string) => ["conflicts", "one", id] as const,
};

export function useConflictSummary(enabled = true) {
  return useQuery({ queryKey: conflictKeys.summary, queryFn: conflicts.summary, enabled });
}

export function useConflicts(status: ConflictStatus) {
  return useQuery({ queryKey: conflictKeys.list(status), queryFn: () => conflicts.list(status) });
}

export function useConflict(id: string | null) {
  return useQuery({
    queryKey: conflictKeys.detail(id ?? ""),
    queryFn: () => conflicts.one(id ?? ""),
    enabled: id !== null,
  });
}

/** Keep a side, dismiss, reopen — each refreshing every list, the summary
 * and the sidebar's count. */
export function useArbitration() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: conflictKeys.all });
  return {
    resolve: useMutation({
      mutationFn: ({
        id,
        side,
        reason,
        remember,
      }: {
        id: string;
        side: number;
        reason?: string;
        remember?: boolean;
      }) => conflicts.resolve(id, { side, reason: reason || null, remember }),
      onSuccess: refresh,
    }),
    dismiss: useMutation({
      mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
        conflicts.dismiss(id, { reason: reason || null }),
      onSuccess: refresh,
    }),
    reopen: useMutation({
      mutationFn: ({ id }: { id: string }) => conflicts.reopen(id),
      onSuccess: refresh,
    }),
  };
}
