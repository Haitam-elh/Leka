"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { accessKeys } from "@/lib/access-queries";
import { protection } from "@/lib/protection";

export const protectionKeys = {
  all: ["data-protection"] as const,
};

export function useDataProtection() {
  return useQuery({ queryKey: protectionKeys.all, queryFn: protection.read });
}

/** The policy changed: read again, and the governance history with it. */
export function useSetProtectionPolicy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (days: number) => protection.setPolicy(days),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: protectionKeys.all });
      void client.invalidateQueries({ queryKey: accessKeys.history });
    },
  });
}
