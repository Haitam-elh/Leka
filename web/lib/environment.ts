/**
 * The workspace's environment, as the "Mon environnement" screens read it
 * (LEKA-359, mockups 10 and 11): what entity resolution and enrichment made
 * of the connected sources — the map, the states, what needs attention,
 * what moved, and one entity's sheet. The shapes are the generated ones.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Environment = components["schemas"]["EnvironmentRead"];
export type EnvironmentNode = components["schemas"]["EnvironmentNodeRead"];
export type EnvironmentEdge = components["schemas"]["EnvironmentEdgeRead"];
export type EnvironmentEvent = components["schemas"]["EnvironmentEventRead"];
export type AttentionPoint = components["schemas"]["AttentionPointRead"];
export type EntitySheet = components["schemas"]["EntitySheetRead"];
export type EntityRef = components["schemas"]["EntityRef"];
export type EntityActivity = components["schemas"]["EntityActivityRead"];
export type EntityActivityEvent = components["schemas"]["EntityActivityEvent"];

/** mockup 10's legend, and a thing with no state of its own. */
export type EnvironmentStatus = "operational" | "attention" | "incident" | "unmonitored";

export const environment = {
  get: () => apiFetch<Environment>("/ingestion/enrichment/environment"),
  sheet: (entityId: string) =>
    apiFetch<EntitySheet>(`/ingestion/enrichment/environment/${entityId}`),
  activity: (entityId: string, days: number) =>
    apiFetch<EntityActivity>(`/ingestion/enrichment/environment/${entityId}/activity?days=${days}`),
};

/**
 * The URL segment of an entity's type — /environment/services/<id> — and
 * back. The sheet reads the entity by its id; the segment says what it is.
 */
export const TYPE_SEGMENTS: Record<string, string> = {
  service: "services",
  repository: "repositories",
  database: "databases",
  infra_resource: "resources",
  incident: "incidents",
  issue: "issues",
  pull_request: "pull-requests",
  commit: "commits",
  document: "documents",
  project: "projects",
  team: "teams",
  person: "people",
  release: "releases",
  branch: "branches",
  deployment: "deployments",
  // The company model's kinds (LEKA-361 → LEKA-367), reached from its views
  // and its search (LEKA-369).
  application: "applications",
  cloud_account: "cloud-accounts",
  resource_group: "resource-groups",
  schema: "schemas",
  data_object: "data-objects",
  knowledge_space: "knowledge-spaces",
  business_capability: "capabilities",
  business_process: "processes",
  change: "changes",
  environment: "environments",
};

export function typeSegment(type: string): string {
  return TYPE_SEGMENTS[type] ?? "entities";
}

/** An entity id is a UUID; anything else in the URL names nothing. */
export function isEntityId(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}
