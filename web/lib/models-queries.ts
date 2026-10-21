"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { models, type WorkspaceModelUpdate } from "@/lib/models";

export const modelKeys = {
  all: ["models"] as const,
  gateway: ["models", "gateway"] as const,
  usage: (days: number) => ["models", "usage", days] as const,
};

export function useModelGateway() {
  return useQuery({ queryKey: modelKeys.gateway, queryFn: models.get });
}

export function useModelUsage(days = 30) {
  return useQuery({ queryKey: modelKeys.usage(days), queryFn: () => models.usage(days) });
}

/** Bring, test, remove the workspace's own model — everything read again. */
export function useModelChange() {
  const client = useQueryClient();
  const again = () => client.invalidateQueries({ queryKey: modelKeys.all });
  return {
    save: useMutation({
      mutationFn: (body: WorkspaceModelUpdate) => models.save(body),
      onSuccess: (gateway) => {
        client.setQueryData(modelKeys.gateway, gateway);
        void again();
      },
    }),
    test: useMutation({ mutationFn: models.test, onSettled: again }),
    remove: useMutation({ mutationFn: models.remove, onSuccess: again }),
  };
}

/** Which of LEKA's models answers first here — one click; the page read
 * again with what answers now (2026-10-21). */
export function useModelDefault() {
  const client = useQueryClient();
  const set = (gateway: Awaited<ReturnType<typeof models.get>>) => {
    client.setQueryData(modelKeys.gateway, gateway);
    void client.invalidateQueries({ queryKey: modelKeys.all });
  };
  return {
    choose: useMutation({
      mutationFn: ({ provider, model }: { provider: string; model: string }) => models.choose(provider, model),
      onSuccess: set,
    }),
    unchoose: useMutation({ mutationFn: models.unchoose, onSuccess: set }),
  };
}

