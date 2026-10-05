"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { insights, type IntelligenceSummary } from "@/lib/insights";

export const insightKeys = {
  summary: ["intelligence", "summary"] as const,
};

/** How long a run asked for is waited for, read again every POLL_MS. */
const WAIT_MS = 2 * 60_000;
const POLL_MS = 4_000;

/** Whether the summary still waits for the run asked at `askedAt`: none
 * started since, or the one that did is still running. */
export function waiting(
  summary: IntelligenceSummary | undefined,
  askedAt: number | null,
  now = Date.now(),
): boolean {
  if (askedAt === null || now - askedAt > WAIT_MS) return false;
  const latest = summary?.latest;
  if (!latest) return true;
  return latest.status === "running" || new Date(latest.started_at).getTime() < askedAt - 1_000;
}

/** The summary, and the way to ask for a run — read again until the run
 * asked for has finished. */
export function useInsights() {
  const client = useQueryClient();
  const [askedAt, setAskedAt] = useState<number | null>(null);
  const summary = useQuery({
    queryKey: insightKeys.summary,
    queryFn: insights.summary,
    refetchInterval: (query) => (waiting(query.state.data, askedAt) ? POLL_MS : false),
  });
  const analyse = useMutation({
    mutationFn: insights.analyse,
    onSuccess: () => {
      setAskedAt(Date.now());
      void client.invalidateQueries({ queryKey: insightKeys.summary });
    },
  });
  return {
    summary,
    analyse,
    waiting: waiting(summary.data, askedAt) || analyse.isPending,
  };
}
