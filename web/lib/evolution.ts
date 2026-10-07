/**
 * The company model's course (LEKA-383): each thing's versions against the
 * one before, its relationships that came and went, what it was at a
 * moment — and the controlled operations on it: a version restored, the
 * model rebuilt, each kept with who asked and what came of it. The shapes
 * are the generated ones; api/leka/api/knowledge.py says what each route
 * answers, docs/company-model.md how the course is kept.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type EntityHistory = components["schemas"]["EntityHistoryRead"];
export type EntityChange = components["schemas"]["EntityChangeRead"];
export type FieldChange = components["schemas"]["FieldChange"];
export type EntityAt = components["schemas"]["EntityAtRead"];
export type Operation = components["schemas"]["OperationRead"];
export type Snapshot = components["schemas"]["SnapshotRead"];

const BASE = "/knowledge";

export const evolution = {
  history: (entityId: string) => apiFetch<EntityHistory>(`${BASE}/entities/${entityId}/history`),
  at: (entityId: string, moment: string) =>
    apiFetch<EntityAt>(
      `${BASE}/entities/${entityId}/at?moment=${encodeURIComponent(moment)}`,
    ),
  snapshots: (since: string) =>
    apiFetch<Snapshot[]>(`${BASE}/snapshots?since=${encodeURIComponent(since)}`),
  restore: (entityId: string, body: { version: number; reason?: string | null }) =>
    apiFetch<Operation>(`${BASE}/entities/${entityId}/restore`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  undo: (operationId: string, body: { reason?: string | null } = {}) =>
    apiFetch<Operation>(`${BASE}/operations/${operationId}/undo`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  rebuild: (body: { reason?: string | null } = {}) =>
    apiFetch<Operation>(`${BASE}/model/rebuild`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/** "attributes.version" → "version"; "name", "lifecycle" as they are. */
export function fieldName(field: string): string {
  return field.startsWith("attributes.") ? field.slice("attributes.".length) : field;
}
