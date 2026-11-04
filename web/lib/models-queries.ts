"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { models, type WorkspaceModelUpdate } from "@/lib/models";

export const modelKeys = {
  all: ["models"] as const,
  settings: ["models", "settings"] as const,
};

/** Whether its contract brings a model of its own, the providers it may
 * bring, its own model (LEKA-530). */
export function useModelSettings() {
  return useQuery({ queryKey: modelKeys.settings, queryFn: models.get });
}

/** Bring, test, remove the workspace's own model — everything read again. */
export function useModelChange() {
  const client = useQueryClient();
  const again = () => client.invalidateQueries({ queryKey: modelKeys.all });
  return {
    save: useMutation({
      mutationFn: (body: WorkspaceModelUpdate) => models.save(body),
      onSuccess: (said) => {
        client.setQueryData(modelKeys.settings, said);
        void again();
      },
    }),
    test: useMutation({ mutationFn: () => models.test(), onSettled: again }),
    remove: useMutation({ mutationFn: () => models.remove(), onSuccess: again }),
  };
}
