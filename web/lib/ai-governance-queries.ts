"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { agentRuns } from "@/lib/agent-runs";
import { agentRunKeys } from "@/lib/agent-runs-queries";
import { aiGovernance, type AIControlUpdate } from "@/lib/ai-governance";

export const aiKeys = {
  all: ["ai-governance"] as const,
  controls: ["ai-governance", "controls"] as const,
  events: ["ai-governance", "events"] as const,
  awaiting: ["agent-runs", "awaiting"] as const,
};

export function useAIControls() {
  return useQuery({ queryKey: aiKeys.controls, queryFn: aiGovernance.controls });
}

export function useAIEvents(enabled: boolean) {
  return useQuery({ queryKey: aiKeys.events, queryFn: aiGovernance.events, enabled });
}

export function useAwaitingRuns() {
  return useQuery({ queryKey: aiKeys.awaiting, queryFn: agentRuns.awaiting });
}

/** A control created, changed, removed — the controls and what they did read again. */
export function useAIControlChange() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: aiKeys.all });
  return {
    create: useMutation({
      mutationFn: (body: AIControlUpdate) => aiGovernance.create(body),
      onSettled: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: AIControlUpdate }) =>
        aiGovernance.update(id, body),
      onSettled: refresh,
    }),
    remove: useMutation({ mutationFn: (id: string) => aiGovernance.remove(id), onSettled: refresh }),
  };
}

/** A held run approved or rejected — the runs and the audit read again. */
export function useRunDecision() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) => agentRuns.decide(id, approve),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: agentRunKeys.all });
      void client.invalidateQueries({ queryKey: aiKeys.all });
    },
  });
}
