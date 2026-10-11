/**
 * The active workspace, and what the signed-in person may do in it.
 *
 * The permission list comes from the API — `GET /api/v1/workspaces/current`
 * returns the workspace, the role and the permissions that role carries.
 * Nothing here recomputes it: the matrix lives in docs/permissions.md, is
 * tested against `ROLE_PERMISSIONS` in the backend, and a second copy in
 * TypeScript would drift from it within a month.
 *
 * The shape is the generated one, so a field renamed on the backend fails
 * `tsc` here rather than reading as `undefined` in a sidebar.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type CurrentWorkspace = components["schemas"]["CurrentWorkspace"];
export type WorkspaceRead = components["schemas"]["WorkspaceRead"];

export const workspace = {
  current: () => apiFetch<CurrentWorkspace>("/workspaces/current", { redirectOn401: false }),
  /** A workspace of one's own, its creator as owner: what someone who
   * belongs to none does first. */
  create: (name: string) =>
    apiFetch<WorkspaceRead>("/workspaces", { method: "POST", body: JSON.stringify({ name }) }),
  /** Change what an admin may: its language, here (docs/languages.md). */
  configure: (changes: { default_language?: string }) =>
    apiFetch<WorkspaceRead>("/workspaces/current", {
      method: "PATCH",
      body: JSON.stringify(changes),
    }),
  /** Make it the workspace this browser works in. */
  enter: (workspaceId: string) =>
    apiFetch<unknown>(`/workspaces/${workspaceId}/switch`, { method: "POST" }),
};
