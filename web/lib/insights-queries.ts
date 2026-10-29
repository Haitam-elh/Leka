"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { insights, type IntelligenceSummary } from "@/lib/insights";
import { LIVE_EVERY } from "@/lib/live";

export const insightKeys = {
  summary: ["intelligence", "summary"] as const,
};

/** How long a run is followed, read again every POLL_MS: until it ends —
 * an analysis of a large workspace takes minutes — fifteen at most. (Two,
 * before 2026-10-09: past them the button said nothing more, the run
 * still going — « analyse en cours, sans jamais s'arrêter ».) */
export const WAIT_MS = 15 * 60_000;
const POLL_MS = 4_000;

/** Whether the summary still waits: a run under way — asked here or not —
 * until it ends; or the run asked at `askedAt`, not started yet. */
export function waiting(
  summary: IntelligenceSummary | undefined,
  askedAt: number | null,
  now = Date.now(),
): boolean {
  const latest = summary?.latest;
  if (latest?.status === "running" && now - Date.parse(latest.started_at) < WAIT_MS) return true;
  if (askedAt === null || now - askedAt > WAIT_MS) return false;
  if (!latest) return true;
  return Date.parse(latest.started_at) < askedAt - 1_000;
}

/** Since when it waits: the run under way's start, else the ask. */
export function waitingSince(
  summary: IntelligenceSummary | undefined,
  askedAt: number | null,
): number | null {
  const latest = summary?.latest;
  if (latest?.status === "running") return Date.parse(latest.started_at);
  return askedAt;
}

/** The summary, and the way to ask for a run — read again until the run
 * asked for has finished. */
export function useInsights() {
  const client = useQueryClient();
  const [askedAt, setAskedAt] = useState<number | null>(null);
  const summary = useQuery({
    queryKey: insightKeys.summary,
    queryFn: insights.summary,
    refetchInterval: (query) => (waiting(query.state.data, askedAt) ? POLL_MS : LIVE_EVERY),
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
    since: waitingSince(summary.data, askedAt),
  };
}
