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

const PROMPT = ["billing", "credits", "prompt"] as const;

/** Past 90 % or 100 % of the month's AI credits, what the reader is offered
 * (LEKA-527): read again every minute and when the page comes back — never
 * on every request. `enabled`: false until the session is known. */
export function useCreditPrompt({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: PROMPT,
    queryFn: billing.creditPrompt,
    enabled,
    refetchInterval: 60_000,
  });
}

/** The prompt put aside: gone at once, the next threshold still to come. */
export function useCreditPromptDismiss() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (threshold: number) => billing.dismissCreditPrompt(threshold),
    onSuccess: () => client.invalidateQueries({ queryKey: PROMPT }),
  });
}

/** The admins asked: the prompt as the server says it after. */
export function useAskUpgrade() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (threshold: number) => billing.askUpgrade(threshold),
    onSuccess: (said) => client.setQueryData(PROMPT, said),
  });
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

