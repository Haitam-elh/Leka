/**
 * Paying for LEKA CORE (LEKA-431): the workspace's subscription, Stripe
 * Checkout for a plan, the customer portal — and the public pricing, the
 * one source of every price shown.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Subscription = components["schemas"]["SubscriptionRead"];
export type Pricing = components["schemas"]["PricingRead"];
export type PricedPlan = components["schemas"]["PlanRead"];
export type CheckoutAnswer = components["schemas"]["CheckoutRead"];

export const subscription = {
  read: () => apiFetch<Subscription>("/billing/subscription"),
  pricing: () => apiFetch<Pricing>("/pricing"),
  checkout: (plan: string, interval: "month" | "year") =>
    apiFetch<CheckoutAnswer>("/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan, interval }),
    }),
  portal: () => apiFetch<{ url: string }>("/billing/portal", { method: "POST" }),
};
