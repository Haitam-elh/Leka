"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type ActionEndpointCreate,
  type ActionEndpointUpdate,
  endpoints,
  isLive,
  plans,
} from "@/lib/actions";
import { decisionKeys } from "@/lib/decisions-queries";
import { intentionKeys } from "@/lib/intentions/queries";

export const planKeys = {
  all: ["plans"] as const,
  of: (intentionId: string) => ["plans", "of", intentionId] as const,
  endpoints: ["action-endpoints"] as const,
};

/** How often a running plan is read again. */
const WHILE_RUNNING = 4_000;

/** An intention's plans, the latest first — read again while one runs. */
export function usePlans(intentionId: string) {
  return useQuery({
    queryKey: planKeys.of(intentionId),
    queryFn: () => plans.of(intentionId),
    enabled: Boolean(intentionId),
    refetchInterval: (query) => (isLive(query.state.data?.[0]) ? WHILE_RUNNING : false),
  });
}

type Act =
  | { kind: "plan" }
  | { kind: "start"; scheduled_for?: string | null; timezone: string }
  | { kind: "cancel"; reason: string }
  | {
      kind: "report";
      stepId: string;
      outcome: "succeeded" | "failed";
      note: string;
      link?: string | null;
    };

/** Plan, start, cancel, report — the plans, the intention it moved and
 * the lists read again. */
export function usePlanAction(intentionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (act: Act) => {
      switch (act.kind) {
        case "plan":
          return plans.plan(intentionId);
        case "start":
          return plans.start(intentionId, {
            scheduled_for: act.scheduled_for ?? null,
            timezone: act.timezone,
          });
        case "cancel":
          return plans.cancel(intentionId, act.reason);
        case "report":
          return plans.report(intentionId, act.stepId, {
            outcome: act.outcome,
            note: act.note,
            link: act.link ?? null,
          });
      }
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: planKeys.of(intentionId) });
      void client.invalidateQueries({ queryKey: intentionKeys.all });
      void client.invalidateQueries({ queryKey: decisionKeys.all });
    },
  });
}

export function useEndpoints(enabled = true) {
  return useQuery({ queryKey: planKeys.endpoints, queryFn: endpoints.list, enabled });
}

export function useEndpointChange() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: planKeys.endpoints });
  return {
    create: useMutation({
      mutationFn: (body: ActionEndpointCreate) => endpoints.create(body),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: ActionEndpointUpdate }) =>
        endpoints.update(id, body),
      onSuccess: refresh,
    }),
    remove: useMutation({ mutationFn: (id: string) => endpoints.remove(id), onSuccess: refresh }),
  };
}
