/**
 * What LEKA proposes to add to the company model, and what was decided of
 * it (LEKA-380): the enrichment candidates — a relationship, an attribute,
 * each with how sure and what shows it — waiting on someone in À valider.
 * The shapes are the generated ones; api/leka/api/intelligence.py says what
 * each route answers, docs/intelligence.md § 13 what each proposal means.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Candidate = components["schemas"]["CandidateRead"];
export type CandidateDetail = components["schemas"]["CandidateDetail"];
export type EnrichmentSummary = components["schemas"]["EnrichmentSummary"];
export type Reprocessed = components["schemas"]["Reprocessed"];
export type CandidateStatus = Candidate["status"];
export type Family = "relationship" | "semantic" | "organisation" | "business";

export const FAMILIES: Family[] = ["relationship", "organisation", "business", "semantic"];
export const STATUSES: CandidateStatus[] = ["proposed", "accepted", "rejected", "withdrawn"];

/** A page of candidates: the API's envelope. */
export interface CandidatePage {
  data: Candidate[];
  next_cursor: string | null;
}

const BASE = "/intelligence/enrichment";

export const enrichment = {
  /** The candidates in a state, the latest seen first — 100 at most. */
  candidates: (status: CandidateStatus) =>
    apiFetch<CandidatePage>(`${BASE}/candidates?status=${status}&limit=100`),
  candidate: (id: string) => apiFetch<CandidateDetail>(`${BASE}/candidates/${id}`),
  summary: () => apiFetch<EnrichmentSummary>(`${BASE}/summary`),
  accept: (id: string, body: { override?: boolean; reason?: string | null }) =>
    apiFetch<CandidateDetail>(`${BASE}/candidates/${id}/accept`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reject: (id: string, body: { reason?: string | null }) =>
    apiFetch<CandidateDetail>(`${BASE}/candidates/${id}/reject`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reprocess: (id: string) =>
    apiFetch<Reprocessed>(`${BASE}/candidates/${id}/reprocess`, { method: "POST" }),
};
