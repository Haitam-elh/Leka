/**
 * The context engine, as the screens inspect it (LEKA-370): the contexts
 * LEKA assembled around an entity, each version whole — every element with
 * its sources and why it is there — what changed between two versions, and
 * the actions that make a version. The shapes are the generated ones;
 * api/leka/api/context.py says what each route answers.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type ContextRead = components["schemas"]["ContextRead"];
export type ContextDetail = components["schemas"]["ContextDetail"];
export type ContextVersion = components["schemas"]["ContextVersionRead"];
export type AssembledContext = components["schemas"]["AssembledContext"];
export type ContextElement = components["schemas"]["ContextElementRead"];
export type ContextDiff = components["schemas"]["ContextDiff"];
export type ContextCreate = components["schemas"]["ContextCreate"];
export type RefreshOutcome = components["schemas"]["RefreshOutcome"];
export type RetrievalMatch = components["schemas"]["RetrievalMatch"];

interface Page<T> {
  data: T[];
  next_cursor: string | null;
}

/** How far a context reaches from its root, in steps (the API takes 1 to 3). */
export const DEPTHS = [1, 2, 3] as const;

/** How many elements a context holds at most: the API's default. */
export const BUDGET = 100;

/** How far back what happened is read, in days (LEKA-371). */
export const WINDOWS = [7, 14, 30, 90] as const;

const post = <T>(path: string, body?: unknown) =>
  apiFetch<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const contexts = {
  /** The contexts of one entity, the latest changed first. */
  ofEntity: (entityId: string) => {
    const search = new URLSearchParams({
      subject_type: "entity",
      subject_id: entityId,
      limit: "20",
    });
    return apiFetch<Page<ContextRead>>(`/context?${search}`).then((page) => page.data);
  },
  detail: (id: string) => apiFetch<ContextDetail>(`/context/${id}`),
  versions: (id: string) =>
    apiFetch<Page<ContextVersion>>(`/context/${id}/versions?limit=50`).then((page) => page.data),
  /** A version whole; the latest that holds something when none is asked. */
  assembled: (id: string, version?: number) =>
    apiFetch<AssembledContext>(
      `/context/${id}/assembled${version ? `?version=${version}` : ""}`,
    ),
  diff: (id: string, from: number, to: number) =>
    apiFetch<ContextDiff>(`/context/${id}/diff?from=${from}&to=${to}`),
  create: (body: ContextCreate) => post<AssembledContext>("/context", body),
  refresh: (id: string) => post<RefreshOutcome>(`/context/${id}/refresh`),
  archive: (id: string) => post<ContextRead>(`/context/${id}/archive`),
};
