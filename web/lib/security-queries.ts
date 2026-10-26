"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { security } from "@/lib/security";
import { sourceKeys } from "@/lib/sources-queries";

export const securityKeys = {
  sessions: ["security", "sessions"] as const,
  usage: (days: number) => ["security", "usage", days] as const,
  journal: ["security", "journal"] as const,
};

export function useDeviceSessions() {
  return useQuery({ queryKey: securityKeys.sessions, queryFn: async () => (await security.sessions()).data });
}

export function useSignOutDevice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => security.signOut(id),
    onSettled: () => client.invalidateQueries({ queryKey: securityKeys.sessions }),
  });
}

export function useRevokeSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (sourceId: string) => security.revoke(sourceId),
    onSettled: () => client.invalidateQueries({ queryKey: sourceKeys.all }),
  });
}

export function useAgentUsage(days: number) {
  return useQuery({ queryKey: securityKeys.usage(days), queryFn: () => security.usage(days) });
}

/** The journal, fifty at a time, the latest first. */
export function useAgentJournal() {
  return useInfiniteQuery({
    queryKey: securityKeys.journal,
    queryFn: ({ pageParam }) => security.journal(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.length === 50 ? last[last.length - 1].queued_at : undefined),
  });
}
