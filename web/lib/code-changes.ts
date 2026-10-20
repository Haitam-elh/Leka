/**
 * Code changes the code-change agent proposed: each file and its diff, for
 * a person to accept — LEKA then opens a pull request — or reject.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type CodeChange = components["schemas"]["CodeChangeRead"];
export type CodeChangeFile = components["schemas"]["CodeChangeFileRead"];
export type CodeChangeFollow = components["schemas"]["CodeChangeFollow"];

export const codeChanges = {
  list: (intentionId: string) =>
    apiFetch<CodeChange[]>(`/code-changes?intention_id=${encodeURIComponent(intentionId)}`),
  forRun: (runId: string) =>
    apiFetch<CodeChange[]>(`/code-changes?run_id=${encodeURIComponent(runId)}`),
  accept: (id: string, note?: string) =>
    apiFetch<CodeChange>(`/code-changes/${encodeURIComponent(id)}/accept`, {
      method: "POST",
      body: JSON.stringify(note ? { note } : {}),
    }),
  /** Its pull request read again on GitHub, read only: its checks, its
   * merge, the deployment that took it. */
  follow: (id: string) =>
    apiFetch<CodeChange>(`/code-changes/${encodeURIComponent(id)}/follow`, { method: "POST" }),
  reject: (id: string, note?: string) =>
    apiFetch<CodeChange>(`/code-changes/${encodeURIComponent(id)}/reject`, {
      method: "POST",
      body: JSON.stringify(note ? { note } : {}),
    }),
};
