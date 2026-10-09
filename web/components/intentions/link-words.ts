import { word } from "@/components/insights/leka-insights";
import type { Dictionary } from "@/lib/i18n/dictionaries";
import type { Finding } from "@/lib/insights";

/**
 * What an intention is linked to, in the reader's words: a finding of
 * LEKA's worded from its code and values as Insights words it — its
 * statement is the API's English (« 3 things rely on postgres-prod… » in a
 * French history, 2026-10-09); anything else, its name.
 */
export function linkedLabel(t: Dictionary, kind: string, label: string, detail: unknown): string {
  const said = (detail ?? {}) as Record<string, unknown>;
  if (kind !== "finding" || typeof said.code !== "string" || !said.params) return label;
  const finding = {
    code: said.code,
    params: said.params as Finding["params"],
    statement: label,
  } as Finding;
  return word(t, finding).title || label;
}
