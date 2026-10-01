/**
 * The customer's connected systems, as the API describes them (LEKA-344).
 *
 * The overview reads them; the sources screen (LEKA-345) manages them —
 * every call of docs/connectors/framework.md's API is here, once. The shapes
 * are the generated ones, so a field renamed on the backend fails `tsc`
 * rather than reading as `undefined` on a card.
 */

import { apiAddress, apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Source = components["schemas"]["SourceRead"];
export type SourceEvent = components["schemas"]["SourceEventRead"];
export type SourceKind = components["schemas"]["SourceKind"];
export type SourceStatus = components["schemas"]["SourceStatus"];
export type CatalogEntry = components["schemas"]["CatalogEntry"];
export type ConnectorCategory = components["schemas"]["ConnectorCategory"];
export type Capability = components["schemas"]["Capability"];
export type Diagnostic = components["schemas"]["Diagnostic"];
export type TestOutcome = components["schemas"]["SourceTestOutcome"];
export type ScopeOptions = components["schemas"]["ScopeOptionsRead"];
export type SourceCreate = components["schemas"]["SourceCreate"];
export type SourceUpdate = components["schemas"]["SourceUpdate"];
export type SourceSync = components["schemas"]["SourceSyncRead"];
export type SourceSyncs = components["schemas"]["SourceSyncs"];
export type SyncSummary = components["schemas"]["SyncSummary"];
export type SyncRun = components["schemas"]["SyncRunRead"];
export type WebhookDelivery = components["schemas"]["WebhookDeliveryRead"];
export type SourceValidation = components["schemas"]["SourceValidation"];

type Page<T> = { data: T[]; next_cursor?: string | null };

/** The API's own ceiling (leka/db/pagination.py). A workspace with more
 * sources than this is not one the overview has to summarise yet. */
const PAGE_SIZE = 200;

const post = <T>(path: string, body?: unknown) =>
  apiFetch<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const sources = {
  list: () => apiFetch<Page<Source>>(`/sources?limit=${PAGE_SIZE}`),
  get: (sourceId: string) => apiFetch<Source>(`/sources/${sourceId}`),
  /** Newest first — the API's default order. */
  events: (sourceId: string, limit = 10) =>
    apiFetch<Page<SourceEvent>>(`/sources/${sourceId}/events?limit=${limit}`),
  /** What can be connected, with the JSON Schemas its form is built from. */
  catalog: () => apiFetch<CatalogEntry[]>("/connectors/catalog"),

  create: (body: SourceCreate) => post<Source>("/sources", body),
  update: (sourceId: string, body: SourceUpdate) =>
    apiFetch<Source>(`/sources/${sourceId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  rotateCredentials: (sourceId: string, credentials: Record<string, string>) =>
    apiFetch<Source>(`/sources/${sourceId}/credentials`, {
      method: "PUT",
      body: JSON.stringify({ credentials }),
    }),
  remove: (sourceId: string) => apiFetch<void>(`/sources/${sourceId}`, { method: "DELETE" }),

  /** 200 either way: a failed test is an answer, with its diagnostic. */
  test: (sourceId: string) => post<TestOutcome>(`/sources/${sourceId}/test`),
  activate: (sourceId: string) => post<Source>(`/sources/${sourceId}/activate`),
  disable: (sourceId: string) => post<Source>(`/sources/${sourceId}/disable`),
  checkHealth: (sourceId: string) => post<unknown>(`/sources/${sourceId}/health-check`),
  /** What the scope can be chosen from, asked of the vendor now. */
  scopeOptions: (sourceId: string) => apiFetch<ScopeOptions>(`/sources/${sourceId}/scope/options`),

  /** Read it now; `queued` is false when a pass is already on its way (LEKA-352). */
  syncNow: (sourceId: string, full = false) =>
    post<{ queued: boolean }>(`/ingestion/sources/${sourceId}/sync?full=${full}`),
  /** Whether a pass is under way, and where each capability stands. */
  syncs: (sourceId: string) => apiFetch<SourceSyncs>(`/ingestion/sources/${sourceId}/syncs`),
  /** One line per source that has been read: records so far, last success. */
  syncSummaries: () => apiFetch<SyncSummary[]>("/ingestion/syncs"),
  /** Its passes, newest first (LEKA-353). */
  runs: (sourceId: string, limit = 10) =>
    apiFetch<Page<SyncRun>>(`/ingestion/sources/${sourceId}/runs?limit=${limit}`),
  /** What its records are worth: valid, doubtful, quarantined, and why (LEKA-358). */
  validation: (sourceId: string) =>
    apiFetch<SourceValidation>(`/ingestion/sources/${sourceId}/validation`),
  /** What a webhook source received, newest first (LEKA-350). Never a body. */
  deliveries: (sourceId: string, limit = 20) =>
    apiFetch<Page<WebhookDelivery>>(`/ingestion/sources/${sourceId}/deliveries?limit=${limit}`),
};

/** Where a webhook source's system sends its deliveries (LEKA-350). */
export function receivingAddress(sourceId: string): string {
  return apiAddress(`/webhooks/sources/${sourceId}`);
}

/**
 * One word for where a source stands, from the three fields that say it.
 *
 *   synced     active, healthy, and its last sync did not fail
 *   attention  degraded, or its last sync failed
 *   error      in error, or unhealthy
 *   setup      still a draft, or tested but not switched on
 *   off        disabled by someone
 */
export type SourceTone = "synced" | "attention" | "error" | "setup" | "off";

export function sourceTone(source: Source): SourceTone {
  if (source.status === "disabled") return "off";
  if (source.status === "draft" || source.status === "tested") return "setup";
  if (source.status === "error" || source.health_status === "unhealthy") return "error";
  if (
    source.status === "degraded" ||
    source.health_status === "degraded" ||
    source.sync_status === "failed"
  ) {
    return "attention";
  }
  return "synced";
}

/** Counted as connected: switched on, whatever its health today. */
export function isConnected(source: Source): boolean {
  return source.status === "active" || source.status === "degraded" || source.status === "error";
}

/** When it was last heard from: its last sync, else its last health check. */
export function lastSeen(source: Source): string | null {
  return source.last_sync_at ?? source.last_health_check_at;
}

/**
 * The mockup's "Type" of each kind of source. Written out, not read from
 * the catalogue: a kind can have sources (the seed's Jira, Slack…) before
 * it has a connector, and `Record` makes a new kind fail `tsc` until it is
 * placed here.
 */
export const KIND_CATEGORY: Record<SourceKind, ConnectorCategory> = {
  github: "code",
  gitlab: "code",
  bitbucket: "code",
  jira: "project",
  linear: "project",
  asana: "project",
  trello: "project",
  clickup: "project",
  monday: "project",
  confluence: "docs",
  notion: "docs",
  slab: "docs",
  guru: "docs",
  google_workspace: "docs",
  microsoft_365: "docs",
  aws: "cloud",
  azure: "cloud",
  gcp: "cloud",
  datadog: "observability",
  pagerduty: "observability",
  grafana: "observability",
  splunk: "observability",
  kibana: "observability",
  postgresql: "data",
  mysql: "data",
  mariadb: "data",
  sqlserver: "data",
  oracle: "data",
  custom_rest: "custom",
  custom_graphql: "custom",
  custom_webhook: "custom",
  supabase: "data",
  mongodb: "data",
  slack: "chat",
};

/** The categories in the order they are shown — Sources' filters, the
 * welcome page's sections. */
export const CATEGORY_ORDER = [
  "code",
  "project",
  "docs",
  "cloud",
  "observability",
  "data",
  "chat",
  "custom",
  "other",
] as const satisfies readonly (ConnectorCategory | "other")[];

/** Can be switched on: tested against the settings it has now. */
export function canActivate(source: Source): boolean {
  return source.status === "tested" || source.status === "disabled";
}

/** Can be read now: switched on, and not waiting for a person. */
export function canSync(source: Source): boolean {
  return source.status === "active" || source.status === "degraded";
}

/** Can be switched off: anything but already off. */
export function canDisable(source: Source): boolean {
  return source.status !== "disabled";
}
