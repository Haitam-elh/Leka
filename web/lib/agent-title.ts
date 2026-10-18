import type { Dictionary } from "@/lib/i18n/dictionaries";

/**
 * An agent's name in the reader's language (LEKA-495): its file names it in
 * French for the model; the interface says it from the dictionary, by its
 * key — an agent the dictionary does not know, as its file names it.
 */
export function agentTitle(t: Dictionary, key: string | null | undefined, fallback: string): string {
  if (!key) return fallback;
  return (t.catalogue.agentTitles as Record<string, string>)[key] ?? fallback;
}
