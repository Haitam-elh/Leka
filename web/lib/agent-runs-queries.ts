"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { agentRuns, MOVING, type AgentRunCreate } from "@/lib/agent-runs";

export const agentRunKeys = {
  all: ["agent-runs"] as const,
  list: (key: string) => ["agent-runs", "list", key] as const,
  intention: (id: string) => ["agent-runs", "intention", id] as const,
  one: (id: string) => ["agent-runs", "one", id] as const,
};

/** How often a run on its way is read again. */
const FOLLOW_MS = 3000;

/** The agents at work on an intention, followed while they are. */
export function useIntentionRuns(intentionId: string) {
  return useQuery({
    queryKey: agentRunKeys.intention(intentionId),
    queryFn: () => agentRuns.forIntention(intentionId),
    enabled: Boolean(intentionId),
    refetchInterval: (query) =>
      query.state.data?.some((run) => MOVING.has(run.status)) ? FOLLOW_MS : false,
  });
}

export function useAgentRuns(key: string) {
  return useQuery({
    queryKey: agentRunKeys.list(key),
    queryFn: () => agentRuns.list(key),
    enabled: Boolean(key),
    refetchInterval: (query) =>
      query.state.data?.some((run) => MOVING.has(run.status)) ? FOLLOW_MS : false,
  });
}

export function useAgentRun(id: string | null) {
  return useQuery({
    queryKey: agentRunKeys.one(id ?? ""),
    queryFn: () => agentRuns.one(id ?? ""),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data && MOVING.has(query.state.data.status) ? FOLLOW_MS : false,
  });
}

/** Run, cancelled — the runs read again. */
export function useAgentRunChange() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: agentRunKeys.all });
  return {
    start: useMutation({
      mutationFn: (body: AgentRunCreate) => agentRuns.start(body),
      onSettled: refresh,
    }),
    cancel: useMutation({
      mutationFn: (id: string) => agentRuns.cancel(id),
      onSettled: refresh,
    }),
  };
}
