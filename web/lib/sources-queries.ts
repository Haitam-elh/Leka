"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { sources } from "@/lib/sources";

/**
 * The sources as queries. Every key starts with "sources", so one
 * invalidation after a change refreshes the list, the panel and the page.
 */
export const sourceKeys = {
  all: ["sources"] as const,
  list: () => [...sourceKeys.all, "list"] as const,
  detail: (id: string) => [...sourceKeys.all, "detail", id] as const,
  events: (id: string) => [...sourceKeys.all, "events", id] as const,
  catalog: () => ["connectors", "catalog"] as const,
};

export function useSources() {
  return useQuery({
    queryKey: sourceKeys.list(),
    queryFn: async () => (await sources.list()).data,
  });
}

export function useSource(id: string) {
  return useQuery({
    queryKey: sourceKeys.detail(id),
    queryFn: () => sources.get(id),
  });
}

export function useSourceEvents(id: string | null, limit = 20) {
  return useQuery({
    queryKey: sourceKeys.events(id ?? ""),
    queryFn: async () => (await sources.events(id ?? "", limit)).data,
    enabled: id !== null,
  });
}

/** Changes rarely: it is the code deployed, not the workspace's data. */
export function useCatalog() {
  return useQuery({
    queryKey: sourceKeys.catalog(),
    queryFn: sources.catalog,
    staleTime: 3_600_000,
  });
}

/** Any change to a source; everything about sources is read again after. */
export function useSourceMutation<TArgs, TResult>(run: (args: TArgs) => Promise<TResult>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => client.invalidateQueries({ queryKey: sourceKeys.all }),
  });
}
