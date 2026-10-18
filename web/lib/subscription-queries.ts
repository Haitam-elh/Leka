"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { subscription } from "@/lib/subscription";

export function useSubscription() {
  return useQuery({ queryKey: ["billing", "subscription"], queryFn: subscription.read });
}

export function usePricing() {
  return useQuery({ queryKey: ["pricing"], queryFn: subscription.pricing, staleTime: 5 * 60_000 });
}

/** Opens Stripe's page — Checkout or the portal — in this tab. */
export function usePayment() {
  return {
    checkout: useMutation({
      mutationFn: ({ plan, interval }: { plan: string; interval: "month" | "year" }) =>
        subscription.checkout(plan, interval),
      onSuccess: ({ url }) => window.location.assign(url),
    }),
    portal: useMutation({
      mutationFn: (cancel?: boolean) => subscription.portal(cancel),
      onSuccess: ({ url }) => window.location.assign(url),
    }),
  };
}

/** Renewed at its period's end, or not — said at once. */
export function useRenewal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (renew: boolean) => subscription.renewal(renew),
    onSuccess: (said) => client.setQueryData(["billing", "subscription"], said),
  });
}

