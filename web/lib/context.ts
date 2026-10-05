/**
 * The context engine, as the screens inspect it (LEKA-370): the contexts
 * LEKA assembled around an entity, each version whole — every element with
 * its sources, why it is there and how it was ranked — what its sources
 * disagree on and what was left out (LEKA-372), what changed between two
 * versions, and the actions that make a version — and the context an
 * intention asks for, as LEKA reads it (LEKA-373) — and how a context keeps
 * up with the company: behind the model or not, widened, narrowed, asked
 * again, every recalculation kept (LEKA-374). The shapes are the generated
 * ones; api/leka/api/context.py says what each route answers.
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
/** An intention, as asked, and what LEKA reads of it (LEKA-373). */
export type IntentAsk = components["schemas"]["IntentAsk"];
export type IntentPlan = components["schemas"]["IntentPlan"];
export type IntentGap = IntentPlan["gaps"][number];
export type IntentSubject = IntentPlan["subjects"][number];
/** Keeping up with the company (LEKA-374). */
export type ContextChange = components["schemas"]["ContextChange"];
export type ContextFreshness = components["schemas"]["ContextFreshness"];
export type ContextCheck = components["schemas"]["ContextCheckRead"];
export type ContextDelta = components["schemas"]["ContextDelta"];
export type ContextExpand = components["schemas"]["ContextExpand"];
export type ContextCompress = components["schemas"]["ContextCompress"];

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

/** Under this score a thing found is left out (LEKA-372): the API's default. */
export const MIN_RELEVANCE = 0.05;

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
  /** Widened — one step when nothing is said — and made again (LEKA-374). */
  expand: ({ id, ask }: { id: string; ask?: ContextExpand }) =>
    post<RefreshOutcome>(`/context/${id}/expand`, ask),
  /** Narrowed — half its budget when nothing is said — and made again. */
  compress: ({ id, ask }: { id: string; ask?: ContextCompress }) =>
    post<RefreshOutcome>(`/context/${id}/compress`, ask),
  /** Made again on its own when the model changes what it holds, or not. */
  follow: ({ id, follow }: { id: string; follow: boolean }) =>
    apiFetch<ContextRead>(`/context/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ follow }),
    }),
  /** Every time it was made again, the latest first. */
  checks: (id: string) =>
    apiFetch<Page<ContextCheck>>(`/context/${id}/checks?limit=20`).then((page) => page.data),
  /** Its intention asked again: the same context, made again. */
  reask: ({ id, ask }: { id: string; ask: IntentAsk }) =>
    post<AssembledContext>(`/context/${id}/intent`, ask),
  /** What an intention asks for, read from its words and scope: nothing kept. */
  planIntent: (ask: IntentAsk) => post<IntentPlan>("/context/intents/plan", ask),
  /** The context an intention asks for, assembled and kept with its plan. */
  intend: (ask: IntentAsk) => post<AssembledContext>("/context/intents", ask),
};
