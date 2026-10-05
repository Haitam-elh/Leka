"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { contexts } from "@/lib/context";

/** The context engine as queries (LEKA-370). */
export const contextKeys = {
  all: ["context"] as const,
  ofEntity: (entityId: string) => [...contextKeys.all, "entity", entityId] as const,
  detail: (id: string) => [...contextKeys.all, "detail", id] as const,
  versions: (id: string) => [...contextKeys.all, "versions", id] as const,
  assembled: (id: string, version: number | null) =>
    [...contextKeys.all, "assembled", id, version] as const,
  diff: (id: string, from: number, to: number) =>
    [...contextKeys.all, "diff", id, from, to] as const,
  checks: (id: string) => [...contextKeys.all, "checks", id] as const,
};

export function useEntityContexts(entityId: string) {
  return useQuery({
    queryKey: contextKeys.ofEntity(entityId),
    queryFn: () => contexts.ofEntity(entityId),
  });
}

export function useContextVersions(id: string | null) {
  return useQuery({
    queryKey: contextKeys.versions(id ?? ""),
    queryFn: () => contexts.versions(id ?? ""),
    enabled: id !== null,
  });
}

/** A version whole — the latest that holds something when `version` is null. */
export function useAssembledContext(id: string | null, version: number | null) {
  return useQuery({
    queryKey: contextKeys.assembled(id ?? "", version),
    queryFn: () => contexts.assembled(id ?? "", version ?? undefined),
    enabled: id !== null,
  });
}

export function useContextDiff(id: string | null, pair: readonly [number, number] | null) {
  return useQuery({
    queryKey: contextKeys.diff(id ?? "", pair?.[0] ?? 0, pair?.[1] ?? 0),
    queryFn: () => contexts.diff(id ?? "", pair?.[0] ?? 0, pair?.[1] ?? 0),
    enabled: id !== null && pair !== null,
  });
}

/** Every time a context was made again, and what came of it (LEKA-374). */
export function useContextChecks(id: string | null) {
  return useQuery({
    queryKey: contextKeys.checks(id ?? ""),
    queryFn: () => contexts.checks(id ?? ""),
    enabled: id !== null,
  });
}

/** Any action on a context; everything about contexts is read again after. */
export function useContextMutation<TArgs, TResult>(run: (args: TArgs) => Promise<TResult>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => client.invalidateQueries({ queryKey: contextKeys.all }),
  });
}
