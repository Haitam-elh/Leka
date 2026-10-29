"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type AlertRuleChange, type AlertRuleWrite, alertRules } from "@/lib/alert-rules";
import { environment, isEntityId } from "@/lib/environment";
import { LIVE_EVERY } from "@/lib/live";
import { monitoring } from "@/lib/twin";

/** The environment as queries (LEKA-359): the screen, and an entity's sheet. */
export const environmentKeys = {
  all: ["environment"] as const,
  sheet: (id: string) => [...environmentKeys.all, "sheet", id] as const,
  activity: (id: string, days: number) => [...environmentKeys.all, "activity", id, days] as const,
};

/** Sources there, never read yet (a demo just opened, a first source just
 * connected): the first reading lands in seconds — asked again until it does. */
export function untilFirstReading(
  env: { sources?: readonly unknown[]; freshness?: { last_read_at?: string | null } | null } | undefined,
): number {
  return env && (env.sources?.length ?? 0) > 0 && !env.freshness?.last_read_at ? 5000 : LIVE_EVERY;
}

export function useEnvironment() {
  return useQuery({
    queryKey: environmentKeys.all,
    queryFn: environment.get,
    refetchInterval: (query) => untilFirstReading(query.state.data),
  });
}

/** An id that is not an entity's asks nothing: the page says it found none. */
export function useEntitySheet(id: string) {
  return useQuery({
    queryKey: environmentKeys.sheet(id),
    queryFn: () => environment.sheet(id),
    enabled: isEntityId(id),
  });
}

/** Everything that moved around an entity over `days` (its tabs Métriques,
 * Déploiements, Logs). */
export function useEntityActivity(id: string, days: number) {
  return useQuery({
    queryKey: environmentKeys.activity(id, days),
    queryFn: () => environment.activity(id, days),
    enabled: isEntityId(id),
  });
}

/** The watch (LEKA-442): what the plan includes, the alerts open and ended. */
export function useMonitoring() {
  return useQuery({ queryKey: ["monitoring"] as const, queryFn: monitoring.get });
}

/** What LEKA went through overnight (2026-10-29). */
export function useNightReview() {
  return useQuery({ queryKey: ["monitoring", "night"] as const, queryFn: monitoring.night });
}

/** Gone through again now: what it found, shown at once. */
export function useNightReviewAgain() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: monitoring.nightAgain,
    onSuccess: (review) => client.setQueryData(["monitoring", "night"], review),
  });
}

/** An alert taken in hand (LEKA-463), the watch read again. */
export function useAcknowledge() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: monitoring.acknowledge,
    onSettled: () => client.invalidateQueries({ queryKey: ["monitoring"] }),
  });
}

/** The alert rules (LEKA-477), and all a screen needs to set one. */
export function useAlertRules(enabled = true) {
  return useQuery({ queryKey: ["monitoring", "rules"] as const, queryFn: alertRules.list, enabled });
}

/** Set, changed, removed, tried: the rules read again. */
export function useAlertRuleChange() {
  const client = useQueryClient();
  const settled = () => client.invalidateQueries({ queryKey: ["monitoring", "rules"] });
  return {
    create: useMutation({ mutationFn: (body: AlertRuleWrite) => alertRules.create(body), onSettled: settled }),
    change: useMutation({
      mutationFn: ({ id, body }: { id: string; body: AlertRuleChange }) => alertRules.change(id, body),
      onSettled: settled,
    }),
    remove: useMutation({ mutationFn: (id: string) => alertRules.remove(id), onSettled: settled }),
    test: useMutation({ mutationFn: (id: string) => alertRules.test(id), onSettled: settled }),
  };
}
