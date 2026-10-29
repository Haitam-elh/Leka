"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { planKeys } from "@/lib/actions-queries";
import { intentionKeys } from "@/lib/intentions/queries";
import { LIVE_EVERY } from "@/lib/live";
import {
  type Expectation,
  isVerifying,
  outcomes,
  type TimelineFilters,
} from "@/lib/outcomes";

export const outcomeKeys = {
  all: ["outcomes"] as const,
  verifications: (intentionId: string) => ["outcomes", "verifications", intentionId] as const,
  // The intention's: whatever moves it — cancelled, voted, run, verified —
  // tells its story again.
  timeline: (intentionId: string, filters: TimelineFilters) =>
    [...intentionKeys.all, "timeline", intentionId, filters] as const,
};

/** How often an outcome being verified is read again: LEKA reads it every
 * five minutes. */
const WHILE_VERIFYING = 30_000;

/** Its verifications, the latest first — read again while one goes on. */
export function useVerifications(intentionId: string, enabled = true) {
  return useQuery({
    queryKey: outcomeKeys.verifications(intentionId),
    queryFn: () => outcomes.verifications(intentionId),
    enabled: Boolean(intentionId) && enabled,
    refetchInterval: (query) => (isVerifying(query.state.data?.[0]) ? WHILE_VERIFYING : LIVE_EVERY),
  });
}

type Act =
  | { kind: "expect"; expectations: readonly Expectation[] }
  | { kind: "check" }
  | { kind: "report"; expectationId: string; met: boolean; note: string; link?: string | null }
  | { kind: "conclude"; note: string };

/** Expect, check, report, conclude — what it moved read again: its plan,
 * the intention, its story. */
export function useOutcomeAction(intentionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (act: Act): Promise<unknown> => {
      switch (act.kind) {
        case "expect":
          return outcomes.expect(intentionId, act.expectations);
        case "check":
          return outcomes.check(intentionId);
        case "report":
          return outcomes.report(intentionId, act.expectationId, {
            met: act.met,
            note: act.note,
            link: act.link ?? null,
          });
        case "conclude":
          return outcomes.conclude(intentionId, act.note);
      }
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: outcomeKeys.all });
      void client.invalidateQueries({ queryKey: planKeys.of(intentionId) });
      void client.invalidateQueries({ queryKey: intentionKeys.all });
    },
  });
}

/** Its whole story, filtered, the latest first. */
export function useTimeline(intentionId: string, filters: TimelineFilters) {
  return useQuery({
    queryKey: outcomeKeys.timeline(intentionId, filters),
    queryFn: () => outcomes.timeline(intentionId, filters),
    enabled: Boolean(intentionId),
  });
}
