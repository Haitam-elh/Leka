"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type CandidateStatus, enrichment } from "@/lib/enrichment";

export const enrichmentKeys = {
  all: ["enrichment"] as const,
  summary: ["enrichment", "summary"] as const,
  list: (status: CandidateStatus) => ["enrichment", "candidates", status] as const,
  detail: (id: string) => ["enrichment", "candidate", id] as const,
};

/** How many wait, were accepted, rejected, withdrawn. */
export function useEnrichmentSummary(enabled = true) {
  return useQuery({ queryKey: enrichmentKeys.summary, queryFn: enrichment.summary, enabled });
}

export function useCandidates(status: CandidateStatus) {
  return useQuery({ queryKey: enrichmentKeys.list(status), queryFn: () => enrichment.candidates(status) });
}

export function useCandidate(id: string | null) {
  return useQuery({
    queryKey: enrichmentKeys.detail(id ?? ""),
    queryFn: () => enrichment.candidate(id ?? ""),
    enabled: id !== null,
  });
}

/** Accept, reject, send back — each refreshing every list, the summary and
 * the sidebar's count. */
export function useDecisions() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: enrichmentKeys.all });
  return {
    accept: useMutation({
      mutationFn: ({ id, override, reason }: { id: string; override?: boolean; reason?: string }) =>
        enrichment.accept(id, { override, reason: reason || null }),
      onSuccess: refresh,
    }),
    reject: useMutation({
      mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
        enrichment.reject(id, { reason: reason || null }),
      onSuccess: refresh,
    }),
    reprocess: useMutation({
      mutationFn: ({ id }: { id: string }) => enrichment.reprocess(id),
      onSuccess: refresh,
    }),
  };
}
