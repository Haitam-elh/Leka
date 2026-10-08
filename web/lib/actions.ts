/**
 * Carrying out what was approved (LEKA-391): an intention's plans — each
 * step, who runs it, how it went, its evidence, every event — and the
 * systems the workspace authorized LEKA to act through.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Plan = components["schemas"]["IntentionPlanRead"];
export type PlanStep = components["schemas"]["IntentionPlanStepRead"];
export type PlanEvent = components["schemas"]["IntentionPlanEventRead"];
export type PlanCheck = components["schemas"]["PlanCheckRead"];
export type ActionEndpoint = components["schemas"]["ActionEndpointRead"];
export type ActionEndpointCreated = components["schemas"]["ActionEndpointCreated"];
export type ActionEndpointCreate = components["schemas"]["ActionEndpointCreate"];
export type ActionEndpointUpdate = components["schemas"]["ActionEndpointUpdate"];

export const plans = {
  of: (intentionId: string) => apiFetch<Plan[]>(`/intentions/${intentionId}/plans`),
  plan: (intentionId: string) =>
    apiFetch<Plan>(`/intentions/${intentionId}/plan`, { method: "POST" }),
  start: (intentionId: string, body: { scheduled_for?: string | null; timezone: string }) =>
    apiFetch<Plan>(`/intentions/${intentionId}/plan/start`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  cancel: (intentionId: string, reason: string) =>
    apiFetch<Plan>(`/intentions/${intentionId}/plan/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  report: (
    intentionId: string,
    stepId: string,
    body: { outcome: "succeeded" | "failed"; note: string; link?: string | null },
  ) =>
    apiFetch<Plan>(`/intentions/${intentionId}/plan/steps/${stepId}/report`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export const endpoints = {
  list: () => apiFetch<ActionEndpoint[]>("/action-endpoints"),
  create: (body: ActionEndpointCreate) =>
    apiFetch<ActionEndpointCreated>("/action-endpoints", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  update: (id: string, body: ActionEndpointUpdate) =>
    apiFetch<ActionEndpoint>(`/action-endpoints/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  remove: (id: string) => apiFetch<void>(`/action-endpoints/${id}`, { method: "DELETE" }),
};

/** The browser's time zone: windows are read in it. */
export function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** On its way: read again every few seconds. */
export function isLive(plan: Plan | undefined): boolean {
  return plan?.status === "running";
}
