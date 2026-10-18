/**
 * What LEKA proposes to send out of a deliverable: tickets for a Jira
 * project, pages for a Confluence space — drafted from what the agent
 * delivered, for a person to choose and accept; LEKA then creates them
 * through the source, when its admin allowed it.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Publication = components["schemas"]["PublicationRead"];
export type PublicationItem = components["schemas"]["PublicationItemRead"];
export type PublicationKind = Publication["kind"];

const post = <T>(path: string, body: unknown) =>
  apiFetch<T>(path, { method: "POST", body: JSON.stringify(body) });

export const publications = {
  forRun: (runId: string) =>
    apiFetch<Publication[]>(`/publications?run_id=${encodeURIComponent(runId)}`),
  ask: (runId: string, body: components["schemas"]["PublicationCreate"]) =>
    post<Publication>(`/agent-runs/${encodeURIComponent(runId)}/publications`, body),
  /** The items chosen, created — every one when none is said. */
  accept: (id: string, items?: string[], note?: string) =>
    post<Publication>(`/publications/${encodeURIComponent(id)}/accept`, {
      ...(items ? { items } : {}),
      ...(note ? { note } : {}),
    }),
  reject: (id: string, note?: string) =>
    post<Publication>(`/publications/${encodeURIComponent(id)}/reject`, note ? { note } : {}),
};
