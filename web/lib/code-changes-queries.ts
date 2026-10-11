"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { codeChanges } from "@/lib/code-changes";

export const codeChangeKeys = {
  all: ["code-changes"] as const,
  intention: (id: string) => ["code-changes", "intention", id] as const,
};

/** An intention's proposed changes — read again every few seconds while
 * an agent may still be proposing one. */
export function useCodeChanges(intentionId: string, following: boolean) {
  return useQuery({
    queryKey: codeChangeKeys.intention(intentionId),
    queryFn: () => codeChanges.list(intentionId),
    enabled: Boolean(intentionId),
    refetchInterval: following ? 4000 : false,
  });
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
