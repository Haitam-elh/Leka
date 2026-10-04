/**
 * One incident, as the company model knows it (LEKA-367): its timeline,
 * what it affects, who handled it, what is said or suspected to have
 * caused it, what changed before it, and what it reaches. The shape is the
 * generated one; api/leka/api/knowledge.py says what the route answers.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type IncidentDetail = components["schemas"]["IncidentDetail"];

export const incidents = {
  detail: (id: string) => apiFetch<IncidentDetail>(`/knowledge/incidents/${id}`),
};
