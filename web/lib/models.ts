/**
 * The workspace's own language model (LEKA-394), under an Enterprise
 * contract that brings it (LEKA-530): whether its contract does, the
 * providers it may bring, its own model if it set one. Never LEKA's models,
 * their prices or what they used: the LEKA team assigns a model to each
 * agent and reads that internally.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type ModelSettings = components["schemas"]["ModelSettingsRead"];
export type ModelProvider = components["schemas"]["ModelProviderRead"];
export type WorkspaceModel = components["schemas"]["WorkspaceModelRead"];
export type WorkspaceModelUpdate = components["schemas"]["WorkspaceModelUpdate"];
export type ModelTest = components["schemas"]["ModelTestRead"];

export const models = {
  get: () => apiFetch<ModelSettings>("/models"),
  save: (body: WorkspaceModelUpdate) =>
    apiFetch<ModelSettings>("/models/settings", { method: "PUT", body: JSON.stringify(body) }),
  remove: () => apiFetch<void>("/models/settings", { method: "DELETE" }),
  test: () => apiFetch<ModelTest>("/models/settings/test", { method: "POST" }),
};

/** A model's name as people say it: « gemini-3.8-flash » → « Gemini 3.8 Flash ». */
export function modelTitle(model: string): string {
  return model
    .replace(/-latest$/, "")
    .split("-")
    .map((part) => (/^[a-z]/.test(part) ? part[0].toUpperCase() + part.slice(1) : part))
    .join(" ");
}
