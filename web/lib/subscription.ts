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
  /** Opened from an intention (LEKA-458): Stripe brings the person back to it. */
  checkout: (plan: string, interval: "month" | "year", intentionId?: string) =>
    apiFetch<CheckoutAnswer>("/billing/checkout", {
      method: "POST",
      body: JSON.stringify(
        intentionId ? { plan, interval, intention_id: intentionId } : { plan, interval },
      ),
    }),
  /** `cancel`: opened on ending the subscription — back to Free (LEKA-490). */
  portal: (cancel = false) =>
    apiFetch<{ url: string }>(cancel ? "/billing/portal?flow=cancel" : "/billing/portal", { method: "POST" }),
  /** « Ne pas renouveler » / « Réactiver le renouvellement » (2026-10-14). */
  renewal: (renew: boolean) =>
    apiFetch<Subscription>("/billing/subscription/renewal", {
      method: "POST",
      body: JSON.stringify({ renew }),
    }),
};
