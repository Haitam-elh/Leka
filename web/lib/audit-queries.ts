"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { audit, type AuditFilters } from "@/lib/audit";

export const auditKeys = {
  all: ["audit"] as const,
  search: (filters: AuditFilters) => ["audit", "search", filters] as const,
  event: (id: string) => ["audit", "event", id] as const,
  settings: ["audit", "settings"] as const,
};

/** The trail, a page at a time, the latest first. */
export function useAuditTrail(filters: AuditFilters) {
  return useInfiniteQuery({
    queryKey: auditKeys.search(filters),
    queryFn: ({ pageParam }) => audit.search(filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next ?? null,
  });
}

export function useAuditEvent(id: string | null) {
  return useQuery({
    queryKey: auditKeys.event(id ?? ""),
    queryFn: () => audit.event(id ?? ""),
    enabled: Boolean(id),
  });
}

export function useAuditSettings() {
  return useQuery({ queryKey: auditKeys.settings, queryFn: audit.settings });
}

/** Kept so long — the trail read again: the change is in it. */
export function useAuditRetention() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (days: number) => audit.keep(days),
    onSettled: () => client.invalidateQueries({ queryKey: auditKeys.all }),
  });
}
