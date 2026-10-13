/**
 * The language model of a workspace (LEKA-394): what answers here — LEKA's
 * default, Gemini 3.8 Flash, its fallbacks — the company's own model if it
 * brings one, and what was asked of models: calls, tokens, estimated cost.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type ModelGateway = components["schemas"]["ModelGatewayRead"];
export type ModelProfile = components["schemas"]["ModelProfileRead"];
export type ModelProvider = components["schemas"]["ModelProviderRead"];
export type WorkspaceModel = components["schemas"]["WorkspaceModelRead"];
export type WorkspaceModelUpdate = components["schemas"]["WorkspaceModelUpdate"];
export type ModelTest = components["schemas"]["ModelTestRead"];
export type ModelUsage = components["schemas"]["ModelUsageRead"];
export type ModelTally = components["schemas"]["ModelTallyRead"];
export type ModelCall = components["schemas"]["ModelCallRead"];

export const models = {
  get: () => apiFetch<ModelGateway>("/models"),
  save: (body: WorkspaceModelUpdate) =>
    apiFetch<ModelGateway>("/models/settings", { method: "PUT", body: JSON.stringify(body) }),
  remove: () => apiFetch<void>("/models/settings", { method: "DELETE" }),
  test: () => apiFetch<ModelTest>("/models/settings/test", { method: "POST" }),
  usage: (days = 30) => apiFetch<ModelUsage>(`/models/usage?days=${days}`),
};

/** A price per million tokens, in dollars, as said: « 0,75 $ ». */
export function dollars(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value > 0 && value < 0.01 ? 4 : 2,
    maximumFractionDigits: value > 0 && value < 0.01 ? 4 : 2,
  }).format(value);
}

/** A cost under a dollar as people say it, in cents: « 1,1 ¢ ». Under a
 * cent, its first two figures — « 0,02 ¢ », never a rounded « 0 ¢ ». */
export function cents(value: number, locale: string): string {
  const said = value * 100;
  const digits = said > 0 && said < 1 ? { maximumSignificantDigits: 2 } : { maximumFractionDigits: 1 };
  return `${new Intl.NumberFormat(locale, digits).format(said)} ¢`;
}

/** A model's name as people say it: « gemini-3.8-flash » → « Gemini 3.8 Flash ». */
export function modelTitle(model: string): string {
  return model
    .replace(/-latest$/, "")
    .split("-")
    .map((part) => (/^[a-z]/.test(part) ? part[0].toUpperCase() + part.slice(1) : part))
    .join(" ");
}
