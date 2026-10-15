"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { type AddOnCheckout, billing } from "@/lib/billing";

export function useWorkspaceUsage() {
  return useQuery({ queryKey: ["billing", "usage"], queryFn: billing.usage });
}

export function useCredits() {
  return useQuery({ queryKey: ["billing", "credits"], queryFn: billing.credits });
}

/** What is sold besides the plan, and what this workspace owns. */
export function useAddOns() {
  return useQuery({ queryKey: ["billing", "add-ons"], queryFn: billing.addOns });
}

export function useEntitlements() {
  return useQuery({ queryKey: ["billing", "entitlements"], queryFn: billing.entitlements });
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

