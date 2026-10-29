"use client";

import { useQuery } from "@tanstack/react-query";

import { LIVE_EVERY } from "@/lib/live";
import { skills } from "@/lib/skills";

export const skillKeys = {
  runs: (ref: string) => ["skills", "runs", ref] as const,
};

/** What LEKA read about one thing — read again while `live`. */
export function useSkillRuns(ref: string, live = false) {
  return useQuery({
    queryKey: skillKeys.runs(ref),
    queryFn: () => skills.runs(ref),
    enabled: Boolean(ref),
    refetchInterval: live ? 4_000 : LIVE_EVERY,
  });
}
