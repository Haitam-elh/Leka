/** Facturation: what the workspace holds and did this month — counted; its plan and AI credits. */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type WorkspaceUsage = components["schemas"]["WorkspaceUsageRead"];
/** Its plan and its AI credits this month (LEKA-430). */
export type Credits = components["schemas"]["CreditsRead"];

/** Agents and bundles sold besides a plan (2026-10-14). */
export type AddOns = components["schemas"]["AddOnsRead"];
export type AgentOffer = components["schemas"]["AgentOfferRead"];
export type BundleOffer = components["schemas"]["BundleOfferRead"];
export type Entitlement = components["schemas"]["EntitlementRead"];
export type AddOnCheckout = components["schemas"]["AddOnCheckoutCreate"];

export const billing = {
  usage: () => apiFetch<WorkspaceUsage>("/billing/usage"),
  credits: () => apiFetch<Credits>("/billing/credits"),
  addOns: () => apiFetch<AddOns>("/billing/add-ons"),
  entitlements: () => apiFetch<Entitlement[]>("/billing/entitlements"),
  /** « Annuler l'abonnement » / « Réactiver le renouvellement » of what was
   * bought with this subscription (LEKA-474): what it owns, said again. */
  addOnRenewal: (subscription: string, renew: boolean) =>
    apiFetch<Entitlement[]>(`/billing/add-ons/${encodeURIComponent(subscription)}/renewal`, {
      method: "POST",
      body: JSON.stringify({ renew }),
    }),
  /** Stripe's page for an agent or a bundle: where to go. */
  buy: (body: AddOnCheckout) =>
    apiFetch<{ url: string }>("/billing/add-ons/checkout", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/** A price, cents a month, as a person reads it: « 15 € ». */
export function euros(cents: number, locale = "fr-FR"): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: cents % 100 ? 2 : 0,
  }).format(cents / 100);
}
