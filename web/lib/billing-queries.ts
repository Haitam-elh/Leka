"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type AddOnCheckout, billing } from "@/lib/billing";

export function useWorkspaceUsage() {
  return useQuery({ queryKey: ["billing", "usage"], queryFn: billing.usage });
}

/** `enabled`: false until the session is known — never a 401 asked for. */
export function useCredits({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: ["billing", "credits"], queryFn: billing.credits, enabled });
}

/** What is sold besides the plan, and what this workspace owns. */
export function useAddOns() {
  return useQuery({ queryKey: ["billing", "add-ons"], queryFn: billing.addOns });
}

export function useEntitlements() {
  return useQuery({ queryKey: ["billing", "entitlements"], queryFn: billing.entitlements });
}

/** An agent's or a bundle's subscription cancelled or renewed: what it owns,
 * as the server says it after. */
export function useAddOnRenewal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ subscription, renew }: { subscription: string; renew: boolean }) =>
      billing.addOnRenewal(subscription, renew),
    onSuccess: (said) => client.setQueryData(["billing", "entitlements"], said),
  });
}

/** Bought: off to Stripe's page — owned once Stripe says it is paid. */
export function useBuy() {
  return useMutation({
    mutationFn: (body: AddOnCheckout) => billing.buy(body),
    onSuccess: ({ url }) => {
      window.location.assign(url);
    },
  });
}

