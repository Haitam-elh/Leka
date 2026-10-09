"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { RUNNING, workflows, type WorkflowRunCreate } from "@/lib/workflows";

export const workflowKeys = {
  all: ["workflows"] as const,
  one: (key: string) => ["workflows", "one", key] as const,
  runs: (key: string) => ["workflows", "runs", key] as const,
  run: (id: string) => ["workflows", "run", id] as const,
};

/** How often a run on its way is read again. */
const FOLLOW_MS = 3000;

export function useWorkflow(key: string) {
  return useQuery({
    queryKey: workflowKeys.one(key),
    queryFn: () => workflows.one(key),
    enabled: Boolean(key),
  });
}

export function useWorkflowRuns(key: string) {
  return useQuery({
    queryKey: workflowKeys.runs(key),
    queryFn: () => workflows.runs(key),
    enabled: Boolean(key),
    refetchInterval: (query) =>
      query.state.data?.some((run) => RUNNING.has(run.status)) ? FOLLOW_MS : false,
  });
}

export function useWorkflowRun(id: string | null) {
  return useQuery({
    queryKey: workflowKeys.run(id ?? ""),
    queryFn: () => workflows.run(id ?? ""),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data && RUNNING.has(query.state.data.status) ? FOLLOW_MS : false,
  });
}

/** Run, cancelled, retried — the runs read again. */
export function useWorkflowChange() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: workflowKeys.all });
  return {
    start: useMutation({
      mutationFn: (body: WorkflowRunCreate) => workflows.start(body),
      onSettled: refresh,
    }),
    cancel: useMutation({ mutationFn: (id: string) => workflows.cancel(id), onSettled: refresh }),
    retry: useMutation({ mutationFn: (id: string) => workflows.retry(id), onSettled: refresh }),
  };
}
