"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type PublicationKind, publications } from "@/lib/publications";

export const publicationKeys = {
  all: ["publications"] as const,
  run: (id: string) => ["publications", "run", id] as const,
};

/** What LEKA proposed to send out of one run — read again while it drafts. */
export function useRunPublications(runId: string | null) {
  return useQuery({
    queryKey: publicationKeys.run(runId ?? ""),
    queryFn: () => publications.forRun(runId ?? ""),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((each) => each.status === "drafting") ? 3000 : false,
  });
}

export function usePublicationActions(runId: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: publicationKeys.all });
  return {
    ask: useMutation({
      mutationFn: (body: { kind: PublicationKind; source_id: string; target: string }) =>
        publications.ask(runId, body),
      onSettled: refresh,
    }),
    accept: useMutation({
      mutationFn: ({ id, items, note }: { id: string; items?: string[]; note?: string }) =>
        publications.accept(id, items, note),
      // Refused whole, it stays proposed and says why: read it again too.
      onSettled: refresh,
    }),
    reject: useMutation({
      mutationFn: ({ id, note }: { id: string; note?: string }) => publications.reject(id, note),
      onSettled: refresh,
    }),
  };
}
