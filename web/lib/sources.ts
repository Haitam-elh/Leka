/**
 * The customer's connected systems, as the API describes them (LEKA-344).
 *
 * Read-only here: the overview shows them, the sources screen will manage
 * them. The shapes are the generated ones, so a field renamed on the backend
 * fails `tsc` rather than reading as `undefined` on a card.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Source = components["schemas"]["SourceRead"];
export type SourceEvent = components["schemas"]["SourceEventRead"];
export type SourceKind = components["schemas"]["SourceKind"];

type Page<T> = { data: T[]; next_cursor?: string | null };

/** The API's own ceiling (leka/db/pagination.py). A workspace with more
 * sources than this is not one the overview has to summarise yet. */
const PAGE_SIZE = 200;

export const sources = {
  list: () => apiFetch<Page<Source>>(`/sources?limit=${PAGE_SIZE}`),
  /** Newest first — the API's default order. */
  events: (sourceId: string, limit = 10) =>
    apiFetch<Page<SourceEvent>>(`/sources/${sourceId}/events?limit=${limit}`),
};

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
