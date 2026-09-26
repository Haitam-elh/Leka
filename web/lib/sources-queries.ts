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
  syncs: (id: string) => [...sourceKeys.all, "syncs", id] as const,
  syncSummaries: () => [...sourceKeys.all, "sync-summaries"] as const,
  runs: (id: string) => [...sourceKeys.all, "runs", id] as const,
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

/** Where each capability of a source stands. Polled while a pass is
 * queued or running — the API says which, from the job itself. */
export function useSourceSyncs(id: string) {
  return useQuery({
    queryKey: sourceKeys.syncs(id),
    queryFn: () => sources.syncs(id),
    refetchInterval: (query) => (query.state.data?.pass_state ? 5_000 : false),
  });
}

/** Records per source, keyed by its id — one call for the whole list. */
export function useSyncSummaries() {
  return useQuery({
    queryKey: sourceKeys.syncSummaries(),
    queryFn: async () =>
      new Map((await sources.syncSummaries()).map((line) => [line.source_id, line])),
  });
}

/** A source's latest passes. Polled while the newest one runs, so its
 * progress — the capability, the records — is seen moving. */
export function useSourceRuns(id: string) {
  return useQuery({
    queryKey: sourceKeys.runs(id),
    queryFn: async () => (await sources.runs(id)).data,
    refetchInterval: (query) => (query.state.data?.[0]?.status === "running" ? 5_000 : false),
  });
}
