"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { capabilities, type CatalogueQuery } from "@/lib/capabilities";

export const capabilityKeys = {
  all: ["capabilities"] as const,
  list: (params: CatalogueQuery) => ["capabilities", "list", params] as const,
  summary: ["capabilities", "summary"] as const,
  one: (key: string) => ["capabilities", "one", key] as const,
};

export function useCapabilities(params: CatalogueQuery) {
  return useQuery({
    queryKey: capabilityKeys.list(params),
    queryFn: () => capabilities.list(params),
  });
}

export function useCatalogueSummary() {
  return useQuery({ queryKey: capabilityKeys.summary, queryFn: capabilities.summary });
}

export function useCapability(key: string) {
  return useQuery({
    queryKey: capabilityKeys.one(key),
    queryFn: () => capabilities.one(key),
    enabled: Boolean(key),
  });
}

/** Turned on or off, kept at hand — the catalogue read again. */
export function useCapabilityChange() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: capabilityKeys.all });
  return {
    settings: useMutation({
      mutationFn: ({ key, enabled, reason }: { key: string; enabled: boolean; reason?: string }) =>
        capabilities.settings(key, { enabled, reason: reason ?? null }),
      onSettled: refresh,
    }),
    favourite: useMutation({
      mutationFn: ({ key, on }: { key: string; on: boolean }) => capabilities.favourite(key, on),
      onSettled: refresh,
    }),
  };
}
