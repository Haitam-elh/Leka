/** Facturation: what the workspace holds and did this month — counted; its plan and AI credits. */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type WorkspaceUsage = components["schemas"]["WorkspaceUsageRead"];
/** Its plan and its AI credits this month (LEKA-430). */
export type Credits = components["schemas"]["CreditsRead"];

export const billing = {
  usage: () => apiFetch<WorkspaceUsage>("/billing/usage"),
  credits: () => apiFetch<Credits>("/billing/credits"),
};
