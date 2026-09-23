/**
 * Where the palette's results will come from.
 *
 * An interface and an empty implementation, on purpose. Searching a
 * customer's environment is the Context Engine's job (LEKA-371 and after);
 * what this ticket owes is the seam and the rule around it.
 *
 * THE RULE. The palette finds and goes. It never answers. A question typed
 * into it — "pourquoi l'API de paiement est lente ?" — is not a search, it
 * is an intention, and the palette offers to create one rather than
 * inventing an answer beside the product's actual workflow.
 */

export interface SearchResult {
  id: string;
  /** What the person reads. */
  label: string;
  /** "Service", "Document", "Source"… — what kind of thing this is. */
  kind: string;
  href: string;
}

export type SearchProvider = (query: string) => Promise<readonly SearchResult[]>;

/** TODO Context Engine: replace with the real provider. */
export const emptySearchProvider: SearchProvider = async () => [];

/**
 * Whether what was typed reads as a question rather than a lookup.
 *
 * Used to put "créer une intention" first: someone asking why something is
 * slow wants the analysis, not a list of files whose name contains "slow".
 */
export function looksLikeAQuestion(query: string): boolean {
  const trimmed = query.trim();
  if (trimmed.length === 0) return false;
  if (trimmed.endsWith("?")) return true;
  if (trimmed.split(/\s+/).length >= 4) return true;
  return /^(pourquoi|comment|quand|qui|que|quel|quelle|est-ce|why|how|when|who|what|which|is|are)\b/i.test(
    trimmed,
  );
}
