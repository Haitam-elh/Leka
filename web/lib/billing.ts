/** Facturation: what the workspace holds and did this month — counted. */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type WorkspaceUsage = components["schemas"]["WorkspaceUsageRead"];

export const billing = {
  usage: () => apiFetch<WorkspaceUsage>("/billing/usage"),
};
