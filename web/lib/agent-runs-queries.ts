"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { agentRuns, MOVING, type AgentRunCreate } from "@/lib/agent-runs";
import { LIVE_EVERY } from "@/lib/live";

export const agentRunKeys = {
  all: ["agent-runs"] as const,
  list: (key: string) => ["agent-runs", "list", key] as const,
  intention: (id: string) => ["agent-runs", "intention", id] as const,
  one: (id: string) => ["agent-runs", "one", id] as const,
  design: (id: string) => ["agent-runs", "design", id] as const,
};

/** How often a run on its way is read again. */
const FOLLOW_MS = 3000;

/** The agents at work on an intention, followed while they are. */
export function useIntentionRuns(intentionId: string, live = false) {
  return useQuery({
    queryKey: agentRunKeys.intention(intentionId),
    queryFn: () => agentRuns.forIntention(intentionId),
    enabled: Boolean(intentionId),
    // Read again while one runs — and while LEKA works on the intention: the
    // agent it hands it to is started by its analysis, after this page
    // first asked. Read once, empty, it was never read again (2026-10-14).
    refetchInterval: (query) =>
      live || query.state.data?.some((run) => MOVING.has(run.status)) ? FOLLOW_MS : LIVE_EVERY,
  });
}

export function useAgentRuns(key: string) {
  return useQuery({
    queryKey: agentRunKeys.list(key),
    queryFn: () => agentRuns.list(key),
    enabled: Boolean(key),
    refetchInterval: (query) =>
      query.state.data?.some((run) => MOVING.has(run.status)) ? FOLLOW_MS : LIVE_EVERY,
  });
}

/** The designer's mock-ups of a run — read once: a run's design never
 * changes, and one that is not there will not come. */
export function useAgentRunDesign(id: string | null) {
  return useQuery({
    queryKey: agentRunKeys.design(id ?? ""),
    queryFn: () => agentRuns.design(id ?? ""),
    enabled: Boolean(id),
    staleTime: Infinity,
    refetchInterval: false,
    retry: false,
  });
}

export function useAgentRun(id: string | null) {
  return useQuery({
    queryKey: agentRunKeys.one(id ?? ""),
    queryFn: () => agentRuns.one(id ?? ""),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data &&
      (MOVING.has(query.state.data.status) ||
        (query.state.data.drawing ?? []).length > 0 ||
        Boolean(query.state.data.correcting))
        ? FOLLOW_MS
        : LIVE_EVERY,
  });
}

/** Its files drawn after it: the run read again until they are there. */
export function useDrawFiles(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (formats: string[]) => agentRuns.drawFiles(id, formats),
    onSuccess: () => client.invalidateQueries({ queryKey: agentRunKeys.one(id) }),
  });
}

/** Its code change written again: the run read again until it is. */
export function useRewriteChange(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => agentRuns.rewriteChange(id),
    onSuccess: () => client.invalidateQueries({ queryKey: agentRunKeys.one(id) }),
  });
}

/** Its mock-ups drawn again: the run read again until they are. */
export function useRedrawDesign(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => agentRuns.redrawDesign(id),
    onSuccess: () => client.invalidateQueries({ queryKey: agentRunKeys.one(id) }),
  });
}

/** One mock-up corrected as asked: the run followed until it is, its
 * design read again then. */
export function useCorrectDesign(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ target, note }: { target: string; note: string }) => agentRuns.correctDesign(id, target, note),
    onSuccess: () => client.invalidateQueries({ queryKey: agentRunKeys.one(id) }),
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
