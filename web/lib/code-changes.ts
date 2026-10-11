/**
 * Code changes the code-change agent proposed: each file and its diff, for
 * a person to accept — LEKA then opens a pull request — or reject.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type CodeChange = components["schemas"]["CodeChangeRead"];
export type CodeChangeFile = components["schemas"]["CodeChangeFileRead"];

export const codeChanges = {
  list: (intentionId: string) =>
    apiFetch<CodeChange[]>(`/code-changes?intention_id=${encodeURIComponent(intentionId)}`),
  accept: (id: string, note?: string) =>
    apiFetch<CodeChange>(`/code-changes/${encodeURIComponent(id)}/accept`, {
      method: "POST",
      body: JSON.stringify(note ? { note } : {}),
    }),
  reject: (id: string, note?: string) =>
    apiFetch<CodeChange>(`/code-changes/${encodeURIComponent(id)}/reject`, {
      method: "POST",
      body: JSON.stringify(note ? { note } : {}),
    }),
};
