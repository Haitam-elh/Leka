"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { access } from "@/lib/access";

export const accessKeys = {
  all: ["access"] as const,
  model: ["access", "model"] as const,
  restrictions: ["access", "restrictions"] as const,
  decisions: (decision: string | null) => ["access", "decisions", decision] as const,
  search: (q: string) => ["access", "search", q] as const,
};

export function useAccessModel() {
  return useQuery({ queryKey: accessKeys.model, queryFn: access.model });
}

export function useRestrictions() {
  return useQuery({ queryKey: accessKeys.restrictions, queryFn: access.restrictions });
}

export function useDecisions(decision: "allow" | "deny" | null) {
  return useQuery({
    queryKey: accessKeys.decisions(decision),
    queryFn: () => access.decisions(decision),
  });
}

export function useEntitySearch(q: string) {
  return useQuery({
    queryKey: accessKeys.search(q),
    queryFn: () => access.search(q),
    enabled: q.trim().length >= 2,
  });
}

/** Restricted, lifted — the restrictions and the trail read again. */
export function useRestrictionChange() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: accessKeys.all });
  return {
    restrict: useMutation({
      mutationFn: ({ entityId, reason }: { entityId: string; reason: string }) =>
        access.restrict(entityId, reason),
      onSettled: refresh,
    }),
    lift: useMutation({ mutationFn: (entityId: string) => access.lift(entityId), onSettled: refresh }),
  };
}
