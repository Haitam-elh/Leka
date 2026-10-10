/**
 * Data protection (LEKA-405): how the platform protects data as it stands,
 * what LEKA found in the workspace's records — kinds and counts, never a
 * value — and how long an original holding one is kept.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type DataProtection = components["schemas"]["DataProtectionRead"];
export type Posture = components["schemas"]["PostureRead"];
export type SourceFindings = components["schemas"]["SourceFindingsRead"];
export type ProtectionPolicy = components["schemas"]["ProtectionPolicyRead"];

export const protection = {
  read: () => apiFetch<DataProtection>("/governance/data-protection"),
  setPolicy: (found_payload_days: number) =>
    apiFetch<ProtectionPolicy>("/governance/data-protection/policy", {
      method: "PUT",
      body: JSON.stringify({ found_payload_days }),
    }),
};
