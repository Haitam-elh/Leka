/**
 * « Demander une compétence » (LEKA-501): an agent or a skill someone wishes
 * LEKA had, sent to LEKA's team — never an intention.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type SuggestionRead = components["schemas"]["SuggestionRead"];
export type SuggestionWrite = components["schemas"]["SuggestionWrite"];

export const suggestions = {
  send: (body: SuggestionWrite) =>
    apiFetch<SuggestionRead>("/capability-suggestions", { method: "POST", body: JSON.stringify(body) }),
};
