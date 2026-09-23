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

export const workspace = {
  current: () => apiFetch<CurrentWorkspace>("/workspaces/current", { redirectOn401: false }),
};
