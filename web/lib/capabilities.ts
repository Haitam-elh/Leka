/**
 * What LEKA can do (LEKA-393): its catalogue — LEKA's own analyses and the
 * agents — for this workspace and this person, each with whether it can be
 * used here and why not, what it takes and delivers, how much it ran.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Capability = components["schemas"]["CapabilityRead"];
export type CapabilityDetail = components["schemas"]["CapabilityDetail"];
export type CatalogueSummary = components["schemas"]["CatalogueSummary"];
export type CapabilityReason = components["schemas"]["CapabilityReason"];
export type CapabilityMatch = components["schemas"]["CapabilityMatch"];

export const CATEGORIES = [
  "architecture",
  "development",
  "infrastructure",
  "operations",
  "security",
  "compliance",
  "data",
  "documentation",
  "project_management",
  "business",
  "knowledge",
] as const;
export type Category = (typeof CATEGORIES)[number];

export const LIFECYCLES = ["draft", "review", "active", "deprecated", "retired"] as const;

export type CatalogueQuery = {
  view?: "all" | "mine";
  category?: string | null;
  q?: string | null;
  sort?: "relevant" | "name" | "recent";
  /** Every lifecycle — what the configuration shows. */
  everything?: boolean;
};

function query(params: CatalogueQuery): string {
  const said = new URLSearchParams();
  if (params.view && params.view !== "all") said.set("view", params.view);
  if (params.category) said.set("category", params.category);
  if (params.q?.trim()) said.set("q", params.q.trim());
  if (params.sort && params.sort !== "relevant") said.set("sort", params.sort);
  if (params.everything) for (const lifecycle of LIFECYCLES) said.append("lifecycle", lifecycle);
  const text = said.toString();
  return text ? `?${text}` : "";
}

export const capabilities = {
  list: (params: CatalogueQuery = {}) => apiFetch<Capability[]>(`/capabilities${query(params)}`),
  summary: () => apiFetch<CatalogueSummary>("/capabilities/summary"),
  one: (key: string) => apiFetch<CapabilityDetail>(`/capabilities/${encodeURIComponent(key)}`),
  settings: (key: string, body: { enabled: boolean; reason?: string | null }) =>
    apiFetch<Capability>(`/capabilities/${encodeURIComponent(key)}/settings`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  favourite: (key: string, on: boolean) =>
    apiFetch<void>(`/capabilities/${encodeURIComponent(key)}/favourite`, {
      method: on ? "PUT" : "DELETE",
    }),
};
